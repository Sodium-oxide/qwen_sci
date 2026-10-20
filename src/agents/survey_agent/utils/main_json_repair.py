"""Repair the outer extraction object while retaining already decoded fields."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Callable


MAIN_FIELDS = ("metadata", "problems", "core_contributions", "core_relations", "components",
               "innovations", "limitations", "future_work")


def _outer_text(response: str) -> str:
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Empty main extraction response")
    body = re.sub(r"^\s*```(?:json)?\s*", "", response.strip(), flags=re.I)
    match = re.search(r"[\[{]", body)
    if match is None:
        raise ValueError("No outer JSON object found")
    return body[match.start():]


def parse_main_object(response: str) -> dict[str, Any]:
    body = _outer_text(response)
    try:
        parsed, _ = json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid outer JSON at character {exc.pos}: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Main extraction response must be a JSON object")
    return parsed


def _completed_fields(response: str) -> dict[str, Any]:
    try:
        body = _outer_text(response)
    except ValueError:
        return {}
    if not body.startswith("{"):
        return {}
    decoder = json.JSONDecoder()
    result = {}
    position = 1
    while position < len(body):
        try:
            position += len(body[position:]) - len(body[position:].lstrip())
            key, position = decoder.raw_decode(body, position)
            position += len(body[position:]) - len(body[position:].lstrip())
            if not isinstance(key, str) or body[position:position + 1] != ":":
                break
            position += 1
            position += len(body[position:]) - len(body[position:].lstrip())
            value, position = decoder.raw_decode(body, position)
            result[key] = value
            position += len(body[position:]) - len(body[position:].lstrip())
            if body[position:position + 1] != ",":
                break
            position += 1
        except (ValueError, IndexError):
            break
    return result


def _repair_state(response: str, error: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    complete = candidate is not None
    candidate = deepcopy(candidate if candidate is not None else _completed_fields(response))
    fields = [field for field in (("metadata",) if complete else MAIN_FIELDS) if field not in candidate]
    if "metadata" in candidate and not isinstance(candidate["metadata"], dict):
        fields.append("metadata")
    if not fields:
        fields = ["core_contributions"]
    return {"candidate": candidate, "fields": fields, "response": response, "error": error}


def _repair_prompt(original: str, state: dict[str, Any], agent: Any, budget: int) -> str:
    excerpt = str(state.get("response") or "")[:8000]

    def build(length: int) -> str:
        request = {"task": "repair_main_extraction_json", "error": state["error"],
                   "fields_to_repair": state["fields"],
                   "protected_fields": sorted(set(state["candidate"]) - set(state["fields"])),
                   "previous_response_excerpt": excerpt[:length],
                   "response_excerpt_is_partial": length < len(str(state.get("response") or ""))}
        return (original + "\n\nThe previous extraction failed JSON/schema validation. The retained paper above is the source. "
                "Repair ONLY the listed top-level fields. Return one JSON object containing those fields. "
                "All other decoded fields are retained by code; do not change or repeat them. "
                "Preserve verbatim evidence, identities and claims. Complete truncated fields from the source. "
                "Do not fabricate closing content or wrap the answer in another object.\n"
                + json.dumps(request, ensure_ascii=False))

    if agent.estimate_tokens(build(0)) > budget:
        raise ValueError("main_json_repair_input_budget_exceeded: full source and repair instructions do not fit")
    low, high = 0, len(excerpt)
    while low < high:
        middle = (low + high + 1) // 2
        if agent.estimate_tokens(build(middle)) <= budget:
            low = middle
        else:
            high = middle - 1
    return build(low)


def _merge_response(response: str, state: dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_main_object(response)
    if state is None:
        return parsed
    previous = state["candidate"]
    fields = set(state["fields"])
    changed = [key for key in parsed if key not in fields
               and (key not in previous or parsed[key] != previous[key])]
    if changed:
        raise ValueError(f"protected_main_fields_changed: {', '.join(sorted(changed))}")
    return {**previous, **{key: value for key, value in parsed.items() if key in fields}}


def extract_main_with_repair(prompts: list[str], metadata: list[dict[str, Any]], agent: Any,
                             validate: Callable, *, max_retry: int, temperature: float,
                             strict_input_budget: bool, max_output_tokens: int,
                             observer: Callable | None = None,
                             initial_states: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    states = {index: deepcopy((initial_states or {}).get(info["paper_id"]))
              for index, info in enumerate(metadata)}
    results = [None] * len(prompts)
    pending = list(range(len(prompts)))
    budget = int(agent.config.APIInfo.llm_max_context_length) - max_output_tokens

    for index, state in states.items():
        if not state or not (state.get("validated") or "received_response" in state):
            continue
        candidate = None
        previous = state.get("previous_state")
        response = state.get("received_response", state.get("response"))
        try:
            candidate = state["candidate"] if state.get("validated") else _merge_response(response, previous)
            valid, result = validate(json.dumps(candidate, ensure_ascii=False), metadata[index])
            if not valid:
                raise ValueError("Main extraction validation failed")
        except (ValueError, TypeError, AttributeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if candidate is not None or previous is None:
                states[index] = _repair_state(response, error, candidate)
            else:
                states[index] = {**previous, "response": response, "error": error}
        else:
            results[index] = result
            pending.remove(index)
    if not pending:
        return results

    def emit(event: dict[str, Any]) -> None:
        if observer is not None:
            observer(event)

    for round_number in range(1, max_retry + 1):
        requests = []
        for index in pending:
            prompt = _repair_prompt(prompts[index], states[index], agent, budget) if states[index] else prompts[index]
            emit({"phase": "request", "paper_id": metadata[index]["paper_id"], "round": round_number,
                  "prompt": prompt, "repair_state": states[index]})
            requests.append(prompt)
        label = f"paper={metadata[pending[0]]['paper_id']} " if len(pending) == 1 else ""
        responses = agent.batch_remote_chat(requests, desc=f"Main extraction {label}round={round_number}/{max_retry}",
            temperature=temperature, strict_input_budget=strict_input_budget, max_output_tokens=max_output_tokens)
        remaining = []
        for position, index in enumerate(pending):
            response = responses[position] if isinstance(responses, list) and position < len(responses) else None
            identity = {"paper_id": metadata[index]["paper_id"], "round": round_number}
            emit({**identity, "phase": "response", "response": response})
            candidate = None
            try:
                candidate = _merge_response(response, states[index])
                valid, result = validate(json.dumps(candidate, ensure_ascii=False), metadata[index])
                if not valid:
                    raise ValueError("Main extraction validation failed")
            except (ValueError, TypeError, AttributeError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                if candidate is not None or not states[index]:
                    states[index] = _repair_state(response, error, candidate)
                else:
                    states[index].update(response=response, error=error)
                emit({**identity, "phase": "outcome", "status": "failed", "error": error,
                      "repair_state": states[index]})
                agent.logger.warning(f"Main extraction paper={identity['paper_id']} round={round_number}/{max_retry}: {error}")
                remaining.append(index)
            else:
                results[index] = result
                emit({**identity, "phase": "outcome", "status": "validated",
                      "repair_state": {"candidate": candidate, "fields": [], "response": response,
                                       "error": "", "validated": True}})
        pending = remaining
        if not pending:
            return results
    details = "; ".join(f"{metadata[index]['paper_id']}: {states[index]['error']}" for index in pending)
    raise ValueError(f"Main extraction failed after {max_retry} attempts: {details}")
