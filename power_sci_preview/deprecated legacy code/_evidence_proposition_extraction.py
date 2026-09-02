"""Contract-agnostic LLM-primary scientific proposition extraction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import unicodedata
from typing import Any, Callable, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

try:
    from .config import SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT
    from ._evidence_assertion_validation import validate_proposition_candidate
    from ._llm import LLMJSONProtocolError
    from .log import log_event
    from ._science_execution_policy import ScienceExecutionPolicy
    from ._science_llm_scheduler import LLMJob, run_science_llm_job
except ImportError:
    from config import SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT
    from _evidence_assertion_validation import validate_proposition_candidate
    from _llm import LLMJSONProtocolError
    from log import log_event
    from _science_execution_policy import ScienceExecutionPolicy
    from _science_llm_scheduler import LLMJob, run_science_llm_job


PROPOSITION_EXTRACTION_SCHEMA_VERSION = "document_proposition_artifact_v7"
SCIENTIFIC_PROPOSITION_SCHEMA_VERSION = "source_bound_scientific_proposition_v5"
PROPOSITION_COVERAGE_REPORT_VERSION = "proposition_coverage_report_v4"
PROPOSITION_PROMPT_REVISION = "scientific_proposition_compact_units_v3"
PROPOSITION_COMPOSITION_PROMPT_REVISION = "scientific_proposition_composition_v4"
SOURCE_BOUND_ASSERTION_CANDIDATE_SCHEMA_VERSION = "source_bound_assertion_candidate_v1"
EVIDENCE_UNIT_REGISTRY_REVISION = "evidence_unit_registry_v1"
MAX_BATCH_SPANS = 24
TARGET_BATCH_SPANS = 10
LONG_SPAN_QUOTE_CHARS = 1000
LONG_SPAN_BATCH_SPANS = 6
SHORT_SPAN_QUOTE_CHARS = 240
SHORT_BATCH_SPANS = 24
MAX_BATCH_QUOTE_CHARS = 40000
MAX_BATCH_PROMPT_CHARS = 55000
MAX_ESTIMATED_OUTPUT_TOKENS = 6500
MAX_PROPOSITIONS_PER_SPAN_ESTIMATE = 3
TERMINAL_TOKENS_PER_SPAN = 80
PROPOSITION_TOKENS_ESTIMATE = 180
REPAIR_MAX_SPANS = 4
_TERMINAL_BATCH_STATUSES = frozenset({
    "PROCESSED",
    "PROCESSED_WITH_REJECTIONS",
    "NO_COMPLETE_PROPOSITION",
})
MAX_COMPOSITION_BATCH = 30
COMPOSITION_OVERLAP = 4

_FIELD_STATUSES = frozenset({
    "COMPLETE", "NOT_APPLICABLE", "NOT_REPORTED", "UNRESOLVED",
    "SOURCE_CORRUPTED", "COMPOSITION_PENDING",
})
_PROCESSED_COVERAGE_STATUSES = frozenset({
    "PROCESSED",
    "PROCESSED_ENTAILMENT_PENDING",
    "NO_COMPLETE_PROPOSITION",
    "PROCESSED_WITH_REJECTIONS",
})
_LEGACY_SOURCE_GROUNDING_FIELDS = frozenset({
    "exact_quote",
    "source_subject_quote",
    "source_predicate_quote",
    "source_object_quote",
})
_COMPACT_PROTOCOL_FORBIDDEN_FIELDS = _LEGACY_SOURCE_GROUNDING_FIELDS | frozenset({
    "source_evidence_quote",
    "quote_char_start",
    "quote_char_end",
    "source_grounding",
})
_PENDING_COVERAGE_STATUSES = frozenset({
    "PENDING_TRANSPORT",
    "PENDING_RESPONSE_TRUNCATED",
    "PENDING_ROOT_PROTOCOL_INVALID",
})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _default_llm_call(**kwargs: Any) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json_contract
    except ImportError:
        from _llm import call_llm_json_contract
    required_list_key = _text(kwargs.get("required_list_key")) or "spans"
    try:
        result = call_llm_json_contract(
            system=str(kwargs["system"]),
            prompt=str(kwargs["prompt"]),
            max_tokens=int(kwargs.get("max_tokens") or 8000),
            required_list_key=required_list_key,
            protocol_name=_text(kwargs.get("protocol_name")) or "PROPOSITION_COMPACT",
            allow_empty=bool(kwargs.get("allow_empty", False)),
            expected_schema_version=_text(kwargs.get("expected_schema_version")),
            allow_partial_recovery=False,
        )
    except LLMJSONProtocolError as exc:
        partial_payload = exc.diagnostics.get("safe_partial_payload")
        if not isinstance(partial_payload, Mapping):
            raise
        diagnostics = dict(exc.diagnostics)
        diagnostics.pop("safe_partial_payload", None)
        return {"payload": dict(partial_payload), "diagnostics": diagnostics}
    return {
        "payload": dict(result["payload"]),
        "diagnostics": dict(result["diagnostics"]),
    }


def proposition_model_id() -> str:
    try:
        from .config import QWEN_MODEL_ID
    except ImportError:
        from config import QWEN_MODEL_ID
    return str(QWEN_MODEL_ID or "")


def _source_span_cache_key(
    span: Mapping[str, Any],
    *,
    document_version_hash: str,
) -> str:
    return "|".join((
        document_version_hash,
        _text(span.get("source_span_id")),
        _extraction_profile(span),
        EVIDENCE_UNIT_REGISTRY_REVISION,
        PROPOSITION_PROMPT_REVISION,
        proposition_model_id(),
    ))


def _pending_status_for_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, LLMJSONProtocolError):
        if error.code.endswith("_RESPONSE_TRUNCATED"):
            return "PENDING_RESPONSE_TRUNCATED", "LLM_PROPOSITION_RESPONSE_TRUNCATED"
        return "PENDING_ROOT_PROTOCOL_INVALID", "LLM_PROPOSITION_ROOT_PROTOCOL_INVALID"
    if isinstance(error, ValueError):
        return "PENDING_ROOT_PROTOCOL_INVALID", "LLM_PROPOSITION_ROOT_PROTOCOL_INVALID"
    return "PENDING_TRANSPORT", "LLM_PROPOSITION_TRANSPORT_PENDING"


def _estimated_output_tokens(batch: list[Mapping[str, Any]]) -> int:
    total = 0
    for span in batch:
        quote_chars = len(str(span.get("quote") or ""))
        estimated_propositions = min(
            MAX_PROPOSITIONS_PER_SPAN_ESTIMATE,
            max(1, (quote_chars + 239) // 240),
        )
        if _extraction_profile(span) != "NARRATIVE_PROPOSITION":
            estimated_propositions = max(estimated_propositions, 2)
        total += TERMINAL_TOKENS_PER_SPAN + (
            estimated_propositions * PROPOSITION_TOKENS_ESTIMATE
        )
    return total


def _unwrap_llm_response(
    response: Any,
    *,
    required_list_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(response, Mapping):
        raise LLMJSONProtocolError(
            "PROPOSITION_COMPACT_ROOT_PROTOCOL_INVALID",
            "LLM response envelope is not an object",
        )
    payload = response.get("payload")
    diagnostics = response.get("diagnostics")
    if isinstance(payload, Mapping):
        if required_list_key not in payload or not isinstance(payload.get(required_list_key), list):
            raise LLMJSONProtocolError(
                "PROPOSITION_COMPACT_ROOT_PROTOCOL_INVALID",
                f"LLM response payload requires a root {required_list_key} array",
                dict(diagnostics or {}),
            )
        return dict(payload), dict(diagnostics or {})
    if required_list_key in response and isinstance(response.get(required_list_key), list):
        return dict(response), {}
    raise LLMJSONProtocolError(
        "PROPOSITION_COMPACT_ROOT_PROTOCOL_INVALID",
        f"LLM response requires a {required_list_key} payload",
        dict(diagnostics or {}),
    )


def _batches(spans: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Pack adjacent compatible spans; chunk ids are context references only."""

    output: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_profile = ""
    for span in spans:
        chars = len(str(span.get("quote") or ""))
        profile = _extraction_profile(span)
        candidate_batch = [*current, span]
        batch_span_limit = _batch_span_limit(candidate_batch)
        if current and (
            profile != current_profile
            or len(current) >= batch_span_limit
            or current_chars + chars > MAX_BATCH_QUOTE_CHARS
            or len(_prompt([*current, span])) > MAX_BATCH_PROMPT_CHARS
            or _estimated_output_tokens([*current, span]) > MAX_ESTIMATED_OUTPUT_TOKENS
        ):
            output.append(current)
            current = []
            current_chars = 0
        current_profile = profile
        current.append(span)
        current_chars += chars
    if current:
        output.append(current)
    return output


def _batch_span_limit(batch: list[Mapping[str, Any]]) -> int:
    configured_limit = max(1, int(MAX_BATCH_SPANS))
    if configured_limit <= TARGET_BATCH_SPANS:
        base_limit = configured_limit
    else:
        base_limit = TARGET_BATCH_SPANS
    quote_lengths = [len(str(span.get("quote") or "")) for span in batch]
    if any(length >= LONG_SPAN_QUOTE_CHARS for length in quote_lengths):
        return min(base_limit, LONG_SPAN_BATCH_SPANS)
    if quote_lengths and max(quote_lengths) <= SHORT_SPAN_QUOTE_CHARS:
        return min(configured_limit, SHORT_BATCH_SPANS)
    return base_limit


def _extraction_profile(span: Mapping[str, Any]) -> str:
    span_kind = _text(span.get("span_kind"))
    if span_kind == "table":
        return "TABLE_ASSERTION"
    if span_kind == "figure_caption":
        return "FIGURE_CAPTION_ASSERTION"
    return "NARRATIVE_PROPOSITION"


def _sentence_ranges(text: str) -> list[tuple[int, int]]:
    if not text:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"[.!?](?=\s|$)", text):
        end = match.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            ranges.append((start, end))
        start = match.end()
    while start < len(text) and text[start].isspace():
        start += 1
    end = len(text)
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        ranges.append((start, end))
    return ranges or [(0, len(text))]


def _source_units_for_span(span: Mapping[str, Any]) -> list[dict[str, Any]]:
    span_id = _text(span.get("source_span_id"))
    quote = str(span.get("quote") or "")
    if not span_id or not quote:
        return []
    ranges = (
        [(0, len(quote))]
        if _extraction_profile(span) != "NARRATIVE_PROPOSITION"
        else _sentence_ranges(quote)
    )
    return [{
        "unit_id": "unit_" + uuid5(
            NAMESPACE_URL,
            "|".join((
                EVIDENCE_UNIT_REGISTRY_REVISION,
                span_id,
                str(start),
                str(end),
            )),
        ).hex[:24],
        "source_span_id": span_id,
        "quote_char_start": start,
        "quote_char_end": end,
        "text": quote[start:end],
    } for start, end in ranges]


def _evidence_unit_registry(
    spans: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        _text(unit.get("unit_id")): unit
        for span in spans
        for unit in _source_units_for_span(span)
        if _text(unit.get("unit_id"))
    }


def _context_window(span: Mapping[str, Any]) -> tuple[str, str]:
    quote = _text(span.get("quote"))
    if not quote or _extraction_profile(span) != "NARRATIVE_PROPOSITION":
        return "", ""
    stripped = quote.lstrip()
    needs_context = (
        not re.search(r"[.!?][\"')\]]?$", quote)
        or (bool(stripped) and stripped[:1].islower())
    )
    if not needs_context:
        return "", ""
    chunk = _text(span.get("llm_chunk_text"))
    start = chunk.find(quote)
    if start < 0:
        return "", ""
    return chunk[max(0, start - 320):start], chunk[start + len(quote):start + len(quote) + 320]


def _context_units_for_span(span: Mapping[str, Any]) -> list[dict[str, Any]]:
    span_id = _text(span.get("source_span_id"))
    before, after = _context_window(span)
    return [{
        "unit_id": "context_" + uuid5(
            NAMESPACE_URL,
            "|".join((
                EVIDENCE_UNIT_REGISTRY_REVISION,
                span_id,
                position,
                text,
            )),
        ).hex[:24],
        "source_span_id": span_id,
        "text": text,
        "role": "CONTEXT_ONLY",
    } for position, text in (("before", before), ("after", after)) if text]


def _prompt_payload(batch: list[dict[str, Any]]) -> dict[str, Any]:
    unit_registry = _evidence_unit_registry(batch)
    prompt_units = [{
        "unit_id": unit_id,
        "source_span_id": unit["source_span_id"],
        "text": unit["text"],
        "role": "EVIDENCE",
    } for unit_id, unit in unit_registry.items()]
    unit_id_by_text = {
        _text(unit.get("text")): _text(unit.get("unit_id"))
        for unit in prompt_units
        if _text(unit.get("text")) and _text(unit.get("unit_id"))
    }
    contexts: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for span in batch:
        span_id = _text(span.get("source_span_id"))
        context_units = _context_units_for_span(span)
        context_id = ""
        if context_units:
            context_unit_ids: list[str] = []
            for context_unit in context_units:
                context_text = _text(context_unit.get("text"))
                existing_unit_id = unit_id_by_text.get(context_text)
                if existing_unit_id:
                    context_unit_ids.append(existing_unit_id)
                    continue
                context_unit_id = _text(context_unit.get("unit_id"))
                prompt_units.append(context_unit)
                unit_id_by_text[context_text] = context_unit_id
                context_unit_ids.append(context_unit_id)
            context_id = f"context_{len(contexts) + 1:04d}"
            contexts.append({
                "context_id": context_id,
                "target_span_id": span_id,
                "unit_ids": context_unit_ids,
            })
        targets.append({
            "span_id": span_id,
            "section_heading": span.get("section_heading"),
            "extraction_profile": _extraction_profile(span),
            "unit_ids": [
                _text(unit.get("unit_id"))
                for unit in _source_units_for_span(span)
            ],
            "context_id": context_id or None,
        })
    return {
        "contexts": contexts,
        "units": prompt_units,
        "targets": targets,
    }


def _prompt(batch: list[dict[str, Any]]) -> str:
    return (
        "Extract every complete scientific proposition stated by the document. Use no research-question context or "
        "external knowledge. Each target span must occur exactly once with status PROPOSITIONS or "
        "NO_COMPLETE_PROPOSITION. For every target span, emit exactly one span record, emit its status before its "
        "propositions, and complete that record before moving to the next span. If the status is "
        "NO_COMPLETE_PROPOSITION, emit no propositions. "
        "A proposition must cite one or more supplied evidence_unit_ids belonging to its "
        "own target span; never copy source text or calculate offsets. Do not invent facts, quantities, attribution, "
        "or causal strength. statement is a normalized complete scientific proposition. triple is optional and, when "
        "present, is [subject,UPPERCASE_RELATION,object]. metadata fields are optional and must be omitted rather "
        "than guessed. Context-only units are disambiguation material and are not a separate evidence source.\n"
        "Return exactly {\"spans\":[{\"span_id\":\"...\",\"status\":\"PROPOSITIONS|NO_COMPLETE_PROPOSITION\","
        "\"propositions\":[{\"evidence_unit_ids\":[\"unit_...\"],\"statement\":\"...\",\"triple\":[\"...\",\"RELATION\",\"...\"],"
        "\"attribution\":\"CURRENT_AUTHORS|CITED_WORK|BACKGROUND|UNSPECIFIED\",\"polarity\":\"POSITIVE|NEGATIVE|MIXED|UNSPECIFIED\","
        "\"modality\":\"ASSERTED|SUGGESTIVE|CONDITIONAL|UNSPECIFIED\",\"completeness\":\"COMPLETE_PROPOSITION|CONTEXT_ONLY|FRAGMENT|METHOD_DESCRIPTION|AUTHOR_LIMITATION\","
        "\"scope\":\"LOCAL_FINDING|SECTION_SYNTHESIS|FULL_DOCUMENT_CONCLUSION\",\"meta\":{\"quantities\":[],\"boundaries\":[],\"limitations\":[]}}]}]}.\n"
        + json.dumps(
            _prompt_payload(batch),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _batch_max_tokens(batch: list[Mapping[str, Any]]) -> int:
    span_count = len(batch)
    if span_count <= 3:
        limit = 3000
    elif span_count <= 8:
        limit = 5000
    elif span_count <= 16:
        limit = 6500
    else:
        limit = 8000
    if any(_extraction_profile(span) != "NARRATIVE_PROPOSITION" for span in batch):
        limit += 800
    return min(limit, 8000)


_SOURCE_CHARACTER_EQUIVALENTS = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2026": "...",
})


def _normalized_source_text(
    value: str,
    *,
    layout: bool,
) -> tuple[str, list[int]]:
    output: list[str] = []
    source_offsets: list[int] = []
    index = 0
    while index < len(value):
        character = value[index]
        if layout and character == "\u00ad":
            index += 1
            continue
        if layout and character == "-" and index > 0 and value[index - 1].isalpha():
            next_index = index + 1
            saw_line_break = False
            while next_index < len(value) and value[next_index].isspace():
                saw_line_break = saw_line_break or value[next_index] in "\r\n"
                next_index += 1
            if (
                saw_line_break
                and next_index < len(value)
                and value[next_index].isalpha()
            ):
                index = next_index
                continue
        normalized = unicodedata.normalize("NFKC", character).translate(
            _SOURCE_CHARACTER_EQUIVALENTS
        )
        for normalized_character in normalized:
            if layout and normalized_character.isspace():
                if output and output[-1] != " ":
                    output.append(" ")
                    source_offsets.append(index)
            else:
                output.append(normalized_character)
                source_offsets.append(index)
        index += 1
    if not layout:
        return "".join(output), source_offsets
    compact_output: list[str] = []
    compact_offsets: list[int] = []
    closing_punctuation = frozenset(",.;:!?%)]}")
    opening_punctuation = frozenset("([{")
    for output_index, character in enumerate(output):
        if character == " ":
            previous = compact_output[-1] if compact_output else ""
            following = output[output_index + 1] if output_index + 1 < len(output) else ""
            if following in closing_punctuation or previous in opening_punctuation:
                continue
        compact_output.append(character)
        compact_offsets.append(source_offsets[output_index])
    return "".join(compact_output), compact_offsets


def _resolve_source_quote(source: str, requested: str) -> dict[str, Any] | None:
    if not requested:
        return None
    direct_start = source.find(requested)
    if direct_start >= 0:
        return {
            "text": source[direct_start:direct_start + len(requested)],
            "source_start": direct_start,
            "source_end": direct_start + len(requested),
            "grounding_mode": "VERBATIM_MATCH",
        }
    for layout, mode in (
        (False, "UNICODE_EQUIVALENT"),
        (True, "LAYOUT_EQUIVALENT"),
    ):
        normalized_source, offsets = _normalized_source_text(source, layout=layout)
        normalized_requested, _ = _normalized_source_text(requested, layout=layout)
        normalized_start = normalized_source.find(normalized_requested)
        if normalized_start < 0 or not normalized_requested:
            continue
        normalized_end = normalized_start + len(normalized_requested)
        source_start = offsets[normalized_start]
        source_end = offsets[normalized_end - 1] + 1
        return {
            "text": source[source_start:source_end],
            "source_start": source_start,
            "source_end": source_end,
            "grounding_mode": mode,
        }
    return None


def _source_anchor(
    value: Any,
    exact_quote: str,
    *,
    field_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    diagnostic_prefix = re.sub(r"[^A-Z0-9]+", "_", field_name.upper()).strip("_")
    if not isinstance(value, str) or not value:
        return None, f"OPTIONAL_{diagnostic_prefix}_DROPPED"
    resolved = _resolve_source_quote(exact_quote, value)
    if resolved is None:
        return None, f"OPTIONAL_{diagnostic_prefix}_DROPPED"
    return resolved, None


def _materialize_candidate_offsets(
    candidate: Mapping[str, Any],
    span: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    hard_errors: list[str] = []
    diagnostics: list[str] = []
    if _LEGACY_SOURCE_GROUNDING_FIELDS.intersection(candidate):
        hard_errors.append("LEGACY_SOURCE_GROUNDING_PROTOCOL_REJECTED")
    span_quote = str(span.get("quote") or "")
    source_evidence_quote = candidate.get("source_evidence_quote")
    if not isinstance(source_evidence_quote, str) or not source_evidence_quote:
        hard_errors.append("SOURCE_EVIDENCE_QUOTE_INVALID")
        exact_quote = ""
        quote_start = -1
        quote_end = -1
        grounding_mode = "UNRESOLVED"
    else:
        resolved_quote = _resolve_source_quote(span_quote, source_evidence_quote)
        if resolved_quote is None:
            hard_errors.append("SOURCE_EVIDENCE_QUOTE_NOT_FOUND_IN_SOURCE_SPAN")
            exact_quote = ""
            quote_start = -1
            quote_end = -1
            grounding_mode = "UNRESOLVED"
        else:
            exact_quote = resolved_quote["text"]
            quote_start = resolved_quote["source_start"]
            quote_end = resolved_quote["source_end"]
            grounding_mode = resolved_quote["grounding_mode"]
    materialized = dict(candidate)
    materialized["quote_char_start"] = quote_start if quote_start >= 0 else None
    materialized["quote_char_end"] = quote_end if quote_end >= 0 else None
    materialized["exact_quote"] = exact_quote
    materialized["source_grounding"] = {
        "mode": grounding_mode,
        "candidate_quote": source_evidence_quote if isinstance(source_evidence_quote, str) else "",
    }
    materialized["subject"] = {"text": "", "source_start": None, "source_end": None}
    materialized["predicate"] = {"text": "", "source_start": None, "source_end": None}
    materialized["object"] = {"text": "", "source_start": None, "source_end": None}
    specialized_source = candidate.get("specialized_fields")
    specialized_source = specialized_source if isinstance(specialized_source, Mapping) else {}
    specialized_fields: dict[str, dict[str, Any]] = {}
    for field_name, value in specialized_source.items():
        normalized_name = _text(field_name)
        if not normalized_name:
            continue
        resolved, diagnostic = _source_anchor(
            value,
            exact_quote,
            field_name=normalized_name,
        )
        if resolved is not None:
            specialized_fields[normalized_name] = resolved
        if diagnostic:
            diagnostics.append(diagnostic)
    materialized["specialized_fields"] = specialized_fields
    structure_values = candidate.get("structure_anchor_quotes")
    if structure_values is not None and not isinstance(structure_values, list):
        diagnostics.append("OPTIONAL_STRUCTURE_ANCHORS_DROPPED")
        structure_values = []
    structure_anchors: list[dict[str, Any]] = []
    for index, value in enumerate(structure_values or []):
        resolved, diagnostic = _source_anchor(
            value,
            exact_quote,
            field_name=f"structure_anchor_{index}",
        )
        if resolved is not None:
            structure_anchors.append(resolved)
        if diagnostic:
            diagnostics.append(diagnostic)
    materialized["structure_anchors"] = structure_anchors
    quantities: list[dict[str, Any]] = []
    raw_quantities = candidate.get("quantities")
    if raw_quantities is not None and not isinstance(raw_quantities, list):
        diagnostics.append("OPTIONAL_QUANTITIES_DROPPED")
        raw_quantities = []
    for index, quantity in enumerate(raw_quantities or []):
        if not isinstance(quantity, Mapping):
            diagnostics.append(f"OPTIONAL_QUANTITY_{index}_DROPPED")
            continue
        current = dict(quantity)
        raw_text = current.get("raw_text")
        if not isinstance(raw_text, str) or not raw_text:
            diagnostics.append(f"OPTIONAL_QUANTITY_{index}_DROPPED")
            continue
        else:
            resolved = _resolve_source_quote(exact_quote, raw_text)
            if resolved is None:
                diagnostics.append(f"OPTIONAL_QUANTITY_{index}_DROPPED")
                continue
            else:
                current["raw_text"] = resolved["text"]
                current["source_start"] = resolved["source_start"]
                current["source_end"] = resolved["source_end"]
                current["grounding_mode"] = resolved["grounding_mode"]
        quantities.append(current)
    materialized["quantities"] = quantities
    for input_field, output_field in (
        ("boundary_condition_quotes", "boundary_conditions"),
        ("comparison_arm_quotes", "comparison_arms"),
        ("limitation_quotes", "limitations"),
    ):
        values = candidate.get(input_field)
        if values is not None and not isinstance(values, list):
            diagnostics.append(f"OPTIONAL_{output_field.upper()}_DROPPED")
            values = []
        resolved_values: list[dict[str, Any]] = []
        for index, value in enumerate(values or []):
            resolved, diagnostic = _source_anchor(
                value,
                exact_quote,
                field_name=f"{output_field}_{index}",
            )
            if resolved is not None:
                resolved_values.append(resolved)
            if diagnostic:
                diagnostics.append(diagnostic)
        materialized[output_field] = resolved_values
    materialized["diagnostic_codes"] = list(dict.fromkeys(diagnostics))
    return materialized, hard_errors


def _composition_batches(
    propositions: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    if len(propositions) < 2:
        return []
    step = max(1, MAX_COMPOSITION_BATCH - COMPOSITION_OVERLAP)
    return [
        propositions[offset:offset + MAX_COMPOSITION_BATCH]
        for offset in range(0, len(propositions), step)
    ]


def _composition_prompt(propositions: list[dict[str, Any]]) -> str:
    fields = (
        "subject", "population_or_system", "phenomenon_or_exposure",
        "intervention_or_cause", "comparator", "outcome_or_effect", "direction",
        "magnitude", "boundary_conditions", "temporal_context", "spatial_context",
        "mechanism", "uncertainty", "evidence_basis", "support_level",
    )
    return (
        "Compose atomic source-grounded propositions only when multiple supplied propositions express different "
        "parts of the same scientific claim. A claim may combine methods, results, discussion, and limitations. "
        "Never merge merely topical statements. Every COMPLETE field must cite one or more supplied proposition ids. "
        "Use NOT_APPLICABLE, NOT_REPORTED, or UNRESOLVED instead of guessing. Return no composition when the atomic "
        "claims should remain separate.\n"
        "Return exactly {\"compositions\":[{\"component_proposition_ids\":[...],"
        "\"proposition_type\":...,\"canonical_statement\":...,\"fields\":{field:{\"value\":...,"
        "\"status\":...,\"source_proposition_ids\":[...]}}}]}. "
        f"Required field names: {json.dumps(fields)}. Allowed field statuses: {json.dumps(sorted(_FIELD_STATUSES))}.\n"
        + json.dumps([
            {
                "proposition_id": item.get("proposition_id"),
                "proposition_type": item.get("proposition_type"),
                "section_heading": item.get("section_heading"),
                "exact_quote": item.get("exact_quote"),
                "canonical_statement": item.get("canonical_statement"),
                "canonical_subject": (item.get("normalization") or {}).get("subject"),
                "canonical_relation": (item.get("normalization") or {}).get("predicate"),
                "canonical_object": (item.get("normalization") or {}).get("object"),
                "specialized_fields": item.get("specialized_fields"),
                "quantities": item.get("quantities"),
                "limitations": item.get("limitations"),
            }
            for item in propositions
        ], ensure_ascii=False)
    )


def _semantic_field(
    raw: Any,
    *,
    component_ids: set[str],
) -> tuple[dict[str, Any], list[str]]:
    source = raw if isinstance(raw, Mapping) else {}
    value = source.get("value")
    status = _text(source.get("status")).upper() or "NOT_REPORTED"
    proposition_ids = [
        _text(item) for item in source.get("source_proposition_ids", [])
        if _text(item)
    ]
    errors: list[str] = []
    if status not in _FIELD_STATUSES:
        errors.append("FIELD_STATUS_INVALID")
        status = "UNRESOLVED"
    if any(item not in component_ids for item in proposition_ids):
        errors.append("FIELD_SOURCE_PROPOSITION_OUTSIDE_COMPOSITION")
    if status == "COMPLETE" and (value in (None, "", []) or not proposition_ids):
        errors.append("COMPLETE_FIELD_REQUIRES_VALUE_AND_SOURCE")
    return {
        "value": value,
        "status": status,
        "source_proposition_ids": proposition_ids,
    }, errors


def _atomic_scientific_proposition(
    atomic: Mapping[str, Any],
) -> dict[str, Any]:
    proposition_id = _text(atomic.get("proposition_id"))
    normalization = atomic.get("normalization")
    normalization = normalization if isinstance(normalization, Mapping) else {}
    subject = _text(normalization.get("subject")) or _text((atomic.get("subject") or {}).get("text"))
    predicate = _text(normalization.get("predicate")) or _text((atomic.get("predicate") or {}).get("text"))
    obj = _text(normalization.get("object")) or _text((atomic.get("object") or {}).get("text"))
    complete = "COMPLETE" if subject else "NOT_REPORTED"
    object_complete = "COMPLETE" if obj else "NOT_REPORTED"
    field = lambda value, status: {
        "value": value,
        "status": status,
        "source_proposition_ids": [proposition_id] if value else [],
    }
    return {
        **dict(atomic),
        "schema_version": SCIENTIFIC_PROPOSITION_SCHEMA_VERSION,
        "canonical_statement": _text(atomic.get("canonical_statement")),
        "component_proposition_ids": [proposition_id],
        "composition_level": "ATOMIC",
        "fields": {
            "subject": field(subject, complete),
            "population_or_system": field(subject, complete),
            "phenomenon_or_exposure": field(predicate, "COMPLETE" if predicate else "NOT_REPORTED"),
            "intervention_or_cause": field("", "NOT_REPORTED"),
            "comparator": field("", "NOT_REPORTED"),
            "outcome_or_effect": field(obj, object_complete),
            "direction": field(_text(atomic.get("polarity")), "COMPLETE" if atomic.get("polarity") else "NOT_REPORTED"),
            "magnitude": field(list(atomic.get("quantities") or []), "COMPLETE" if atomic.get("quantities") else "NOT_REPORTED"),
            "boundary_conditions": field(list(atomic.get("boundary_conditions") or []), "COMPLETE" if atomic.get("boundary_conditions") else "NOT_REPORTED"),
            "temporal_context": field("", "NOT_REPORTED"),
            "spatial_context": field("", "NOT_REPORTED"),
            "mechanism": field("", "NOT_REPORTED"),
            "uncertainty": field(list(atomic.get("limitations") or []), "COMPLETE" if atomic.get("limitations") else "NOT_REPORTED"),
            "evidence_basis": field(_text(atomic.get("assertion_kind")), "COMPLETE"),
            "support_level": field(_text(atomic.get("validator_verdict")), "COMPLETE"),
        },
        "source_evidence": [{
            "proposition_id": proposition_id,
            "source_span_id": atomic.get("source_span_id"),
            "exact_quote": atomic.get("exact_quote"),
            "quote_char_start": atomic.get("quote_char_start"),
            "quote_char_end": atomic.get("quote_char_end"),
            "source_grounding": dict(atomic.get("source_grounding") or {}),
        }],
        "semantic_entailment": {
            "schema_version": "semantic_entailment_status_v1",
            "verdict": "ENTAILED",
            "method": "SOURCE_BOUND_EXTRACTION_VALIDATOR",
            "reason": "The canonical proposition was accepted only with a locatable source quote; contract relevance is audited separately.",
        },
    }


def _compose_document_propositions(
    atomic_propositions: list[dict[str, Any]],
    *,
    llm_call: Callable[..., dict[str, Any]],
    composition_candidates: Iterable[Mapping[str, Any]] = (),
) -> tuple[
    list[dict[str, Any]],
    list[str],
    int,
    list[dict[str, Any]],
]:
    scientific = [_atomic_scientific_proposition(item) for item in atomic_propositions]
    by_id = {
        _text(item.get("proposition_id")): item
        for item in atomic_propositions
        if _text(item.get("proposition_id"))
    }
    errors: list[str] = []
    unresolved_component_ids: set[str] = set()
    rejected_compositions: list[dict[str, Any]] = []
    seen_components: set[tuple[str, ...]] = set()
    field_names = tuple(scientific[0]["fields"]) if scientific else ()
    eligible_composition_candidates = [
        dict(item)
        for item in composition_candidates
        if isinstance(item, Mapping)
    ]
    for batch_index, batch in enumerate(
        _composition_batches(eligible_composition_candidates)
    ):
        batch_id = f"composition_{batch_index + 1:04d}"
        prompt = _composition_prompt(batch)
        candidate_id = _text(batch[0].get("paper_id")) if batch else "unknown_document"
        batch_ids = {_text(item.get("proposition_id")) for item in batch}
        try:
            response = run_science_llm_job(
                LLMJob(
                    candidate_id=candidate_id,
                    stage="proposition_composition",
                    batch_id=batch_id,
                    prompt_chars=len(prompt),
                    max_tokens=5000,
                    input_span_count=len(batch),
                ),
                lambda: llm_call(
                    system=(
                        "You compose complete scientific propositions from validated atomic source propositions. "
                        "Return JSON only and never add facts not present in the supplied atoms."
                    ),
                    prompt=prompt,
                    max_tokens=5000,
                    required_list_key="compositions",
                    protocol_name="PROPOSITION_COMPOSITION",
                    allow_empty=True,
                ),
            )
        except Exception as exc:
            errors.append(f"LLM_PROPOSITION_COMPOSITION_PENDING:{batch_id}:{type(exc).__name__}")
            unresolved_component_ids.update(batch_ids)
            continue
        try:
            payload, _ = _unwrap_llm_response(
                response,
                required_list_key="compositions",
            )
        except Exception:
            errors.append(f"LLM_PROPOSITION_COMPOSITION_PROTOCOL_INVALID:{batch_id}")
            unresolved_component_ids.update(batch_ids)
            continue
        compositions = payload.get("compositions")
        if not isinstance(compositions, list):
            errors.append(f"LLM_PROPOSITION_COMPOSITION_PROTOCOL_INVALID:{batch_id}")
            unresolved_component_ids.update(batch_ids)
            continue
        for composition_index, composition in enumerate(compositions):
            if not isinstance(composition, Mapping):
                rejected_compositions.append({
                    "candidate_stage": "PROPOSITION_COMPOSITION",
                    "batch_id": batch_id,
                    "candidate_index": composition_index,
                    "terminal_status": "REJECTED_TERMINAL",
                    "validator_verdict": "REJECTED",
                    "validator_reason_codes": ["COMPOSITION_CANDIDATE_NOT_OBJECT"],
                })
                continue
            component_ids = tuple(dict.fromkeys(
                _text(item) for item in composition.get("component_proposition_ids", []) if _text(item)
            ))
            if len(component_ids) < 2 or any(item not in batch_ids for item in component_ids):
                errors.append(f"COMPOSITION_COMPONENT_SET_INVALID:{batch_id}")
                rejected_compositions.append({
                    "candidate_stage": "PROPOSITION_COMPOSITION",
                    "batch_id": batch_id,
                    "candidate_index": composition_index,
                    "component_proposition_ids": list(component_ids),
                    "terminal_status": "REJECTED_TERMINAL",
                    "validator_verdict": "REJECTED",
                    "validator_reason_codes": ["COMPOSITION_COMPONENT_SET_INVALID"],
                })
                continue
            signature = tuple(sorted(component_ids))
            if signature in seen_components:
                continue
            statement = _text(composition.get("canonical_statement"))
            if not statement:
                errors.append(f"COMPOSITION_STATEMENT_MISSING:{batch_id}")
                rejected_compositions.append({
                    "candidate_stage": "PROPOSITION_COMPOSITION",
                    "batch_id": batch_id,
                    "candidate_index": composition_index,
                    "component_proposition_ids": list(component_ids),
                    "terminal_status": "REJECTED_TERMINAL",
                    "validator_verdict": "REJECTED",
                    "validator_reason_codes": ["COMPOSITION_STATEMENT_MISSING"],
                })
                continue
            component_set = set(component_ids)
            raw_fields = composition.get("fields") if isinstance(composition.get("fields"), Mapping) else {}
            fields: dict[str, Any] = {}
            field_errors: list[str] = []
            for field_name in field_names:
                fields[field_name], current_errors = _semantic_field(
                    raw_fields.get(field_name), component_ids=component_set
                )
                field_errors.extend(f"{field_name}:{error}" for error in current_errors)
            if field_errors:
                errors.extend(f"COMPOSITION_FIELD_INVALID:{batch_id}:{error}" for error in field_errors)
                rejected_compositions.append({
                    "candidate_stage": "PROPOSITION_COMPOSITION",
                    "batch_id": batch_id,
                    "candidate_index": composition_index,
                    "component_proposition_ids": list(component_ids),
                    "terminal_status": "REJECTED_TERMINAL",
                    "validator_verdict": "REJECTED",
                    "validator_reason_codes": [
                        f"COMPOSITION_FIELD_INVALID:{error}" for error in field_errors
                    ],
                })
                continue
            components = [by_id[item] for item in component_ids]
            source_span_ids = list(dict.fromkeys(
                span_id
                for item in components
                for span_id in item.get("source_span_ids", [])
                if span_id
            ))
            proposition_id = "prop_composed_" + uuid5(
                NAMESPACE_URL,
                "|".join((
                    _text(components[0].get("document_version_hash")),
                    *sorted(component_ids),
                    statement,
                )),
            ).hex[:24]
            scientific.append({
                "schema_version": SCIENTIFIC_PROPOSITION_SCHEMA_VERSION,
                "proposition_id": proposition_id,
                "proposition_type": _text(composition.get("proposition_type")).upper() or "AUTHOR_INTERPRETATION",
                "canonical_statement": statement,
                "paper_id": components[0].get("paper_id"),
                "document_version_hash": components[0].get("document_version_hash"),
                "component_proposition_ids": list(component_ids),
                "composition_level": "COMPOSED",
                "fields": fields,
                "source_span_ids": source_span_ids,
                "source_unit_ids": list(source_span_ids),
                "source_evidence": [
                    {
                        "proposition_id": item.get("proposition_id"),
                        "source_span_id": item.get("source_span_id"),
                        "exact_quote": item.get("exact_quote"),
                        "quote_char_start": item.get("quote_char_start"),
                        "quote_char_end": item.get("quote_char_end"),
                        "source_grounding": dict(item.get("source_grounding") or {}),
                    }
                    for item in components
                ],
                "source_locations": [
                    location
                    for item in components
                    for location in item.get("source_locations", [])
                ],
                "validator_verdict": "ACCEPTED_SOURCE_BOUND",
                "validator_reason_codes": [],
                "semantic_entailment": {
                    "schema_version": "semantic_entailment_status_v1",
                    "verdict": "ENTAILED",
                    "method": "SOURCE_BOUND_COMPOSITION_VALIDATOR",
                    "reason": "The composition is restricted to accepted source-bound component propositions; contract relevance is audited separately.",
                },
                "claim_scope": "SECTION_SYNTHESIS",
                "extraction_method": "llm_atomic_then_cross_span_composition_v3",
                "model_id": proposition_model_id(),
                "prompt_revision": {
                    "atomic": PROPOSITION_PROMPT_REVISION,
                    "composition": PROPOSITION_COMPOSITION_PROMPT_REVISION,
                },
            })
            seen_components.add(signature)
    return scientific, errors, len(unresolved_component_ids), rejected_compositions


def _source_bound_assertion_candidates(
    propositions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist source-grounded assertion candidates before contract alignment."""
    candidates: list[dict[str, Any]] = []
    for proposition in propositions:
        proposition_id = _text(proposition.get("proposition_id"))
        document_version_hash = _text(proposition.get("document_version_hash"))
        if not proposition_id or not document_version_hash:
            continue
        candidates.append({
            "schema_version": SOURCE_BOUND_ASSERTION_CANDIDATE_SCHEMA_VERSION,
            "assertion_candidate_id": "assertcand_" + uuid5(
                NAMESPACE_URL,
                f"{document_version_hash}|{proposition_id}",
            ).hex[:24],
            "proposition_id": proposition_id,
            "paper_id": _text(proposition.get("paper_id")),
            "document_version_hash": document_version_hash,
            "source_span_ids": list(proposition.get("source_span_ids") or []),
            "source_evidence": [
                dict(item)
                for item in proposition.get("source_evidence", [])
                if isinstance(item, Mapping)
            ],
            "canonical_statement": _text(proposition.get("canonical_statement")),
            "claim_role": _text(proposition.get("claim_role")),
            "status": "ALIGNMENT_PENDING",
            "validator_verdict": "SOURCE_BOUND",
            "semantic_entailment_status": _text(
                (proposition.get("semantic_entailment") or {}).get("verdict")
            ).upper() or "PENDING",
            "counts_toward_gate": False,
            "direct_slot_eligible": False,
        })
    return candidates


def _compact_candidate_materialization(
    candidate: Mapping[str, Any],
    *,
    span_id: str,
    span: Mapping[str, Any],
    units_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    if _COMPACT_PROTOCOL_FORBIDDEN_FIELDS.intersection(candidate):
        return None, ["COMPACT_PROTOCOL_FORBIDDEN_SOURCE_FIELD"], []
    unit_ids = [
        _text(value) for value in candidate.get("evidence_unit_ids", [])
        if _text(value)
    ] if isinstance(candidate.get("evidence_unit_ids"), list) else []
    if not unit_ids:
        return None, ["EVIDENCE_UNIT_IDS_MISSING"], []
    if len(unit_ids) != len(set(unit_ids)):
        return None, ["EVIDENCE_UNIT_IDS_DUPLICATE"], []
    units = [units_by_id.get(unit_id) for unit_id in unit_ids]
    if any(
        not isinstance(unit, Mapping)
        or _text(unit.get("source_span_id")) != span_id
        for unit in units
    ):
        return None, ["EVIDENCE_UNIT_NOT_OWNED_BY_TARGET_SPAN"], []
    ordered = sorted(
        (dict(unit) for unit in units if isinstance(unit, Mapping)),
        key=lambda unit: int(unit.get("quote_char_start") or 0),
    )
    expected = sorted(
        (
            unit for unit in units_by_id.values()
            if _text(unit.get("source_span_id")) == span_id
        ),
        key=lambda unit: int(unit.get("quote_char_start") or 0),
    )
    expected_ids = [_text(unit.get("unit_id")) for unit in expected]
    selected_indexes = [expected_ids.index(_text(unit.get("unit_id"))) for unit in ordered]
    if selected_indexes != list(range(selected_indexes[0], selected_indexes[-1] + 1)):
        return None, ["EVIDENCE_UNITS_NOT_CONTIGUOUS"], []
    quote = str(span.get("quote") or "")
    start = int(ordered[0].get("quote_char_start") or 0)
    end = int(ordered[-1].get("quote_char_end") or 0)
    if not (0 <= start < end <= len(quote)):
        return None, ["EVIDENCE_UNIT_RANGE_INVALID"], []
    triple = candidate.get("triple")
    if triple is None:
        triple = ["", "", ""]
    if not isinstance(triple, list) or len(triple) != 3:
        return None, ["PROPOSITION_TRIPLE_INVALID"], []
    meta = candidate.get("meta") if isinstance(candidate.get("meta"), Mapping) else {}
    unit_text_by_id = {
        _text(unit.get("unit_id")): _text(unit.get("text"))
        for unit in ordered
    }
    boundary_ids = meta.get("boundaries") if isinstance(meta.get("boundaries"), list) else []
    limitation_ids = meta.get("limitations") if isinstance(meta.get("limitations"), list) else []
    materialized = {
        "source_span_id": span_id,
        "source_evidence_quote": quote[start:end],
        "canonical_statement": _text(candidate.get("statement")),
        "canonical_subject": _text(triple[0]),
        "canonical_relation": _text(triple[1]),
        "canonical_object": _text(triple[2]),
        "proposition_type": _text(candidate.get("kind")) or "SOURCE_BOUND_CLAIM",
        "assertion_kind": _text(candidate.get("kind")) or "SOURCE_BOUND_CLAIM",
        "polarity": _text(candidate.get("polarity")) or "UNSPECIFIED",
        "modality": _text(candidate.get("modality")) or "UNSPECIFIED",
        "attribution": _text(candidate.get("attribution")) or "UNSPECIFIED",
        "claim_completeness": _text(candidate.get("completeness")) or "COMPLETE_PROPOSITION",
        "claim_scope": _text(candidate.get("scope")) or "LOCAL_FINDING",
        "extraction_profile": _extraction_profile(span),
        "quantities": list(meta.get("quantities") or []),
        "boundary_condition_quotes": [
            unit_text_by_id[unit_id]
            for unit_id in boundary_ids
            if unit_id in unit_text_by_id
        ],
        "limitation_quotes": [
            unit_text_by_id[unit_id]
            for unit_id in limitation_ids
            if unit_id in unit_text_by_id
        ],
        "comparison_arm_quotes": [],
        "specialized_fields": {},
        "structure_anchor_quotes": [],
    }
    return materialized, [], unit_ids


def _validate_compact_batch(
    payload: Any,
    *,
    batch_span_ids: set[str],
    spans_by_id: Mapping[str, Mapping[str, Any]],
    units_by_id: Mapping[str, Mapping[str, Any]],
    document_version_hash: str,
    extraction_run_id: str,
    attempt: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    bool,
]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    terminals: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, Mapping) or not isinstance(payload.get("spans"), list):
        return accepted, [{
            "validator_verdict": "REJECTED_PROTOCOL",
            "validator_reason_codes": ["COMPACT_SPAN_ROOT_INVALID"],
            "protocol_attempt": attempt,
        }], terminals, False
    records_by_span: dict[str, list[Mapping[str, Any]]] = {}
    for record in payload["spans"]:
        if not isinstance(record, Mapping):
            rejected.append({
                "validator_verdict": "REJECTED_PROTOCOL",
                "validator_reason_codes": ["COMPACT_SPAN_RECORD_NOT_OBJECT"],
                "protocol_attempt": attempt,
            })
            continue
        span_id = _text(record.get("span_id"))
        if span_id not in batch_span_ids:
            rejected.append({
                "source_span_id": span_id,
                "validator_verdict": "REJECTED_PROTOCOL",
                "validator_reason_codes": ["COMPACT_SPAN_OUTSIDE_CURRENT_BATCH"],
                "protocol_attempt": attempt,
            })
            continue
        records_by_span.setdefault(span_id, []).append(record)
    for span_id in batch_span_ids:
        records = records_by_span.get(span_id, [])
        if len(records) != 1:
            terminals[span_id] = {
                "status": "PENDING_ROOT_PROTOCOL_INVALID",
                "reason_codes": [
                    "COMPACT_SPAN_RESPONSE_MISSING"
                    if not records else "COMPACT_SPAN_RESPONSE_DUPLICATE"
                ],
            }
            continue
        record = records[0]
        status = _text(record.get("status")).upper()
        raw_candidates = record.get("propositions")
        if status not in {"PROPOSITIONS", "NO_COMPLETE_PROPOSITION"} or not isinstance(raw_candidates, list):
            terminals[span_id] = {
                "status": "PENDING_ROOT_PROTOCOL_INVALID",
                "reason_codes": ["COMPACT_SPAN_TERMINAL_INVALID"],
            }
            continue
        if status == "NO_COMPLETE_PROPOSITION":
            if raw_candidates:
                terminals[span_id] = {
                    "status": "PENDING_ROOT_PROTOCOL_INVALID",
                    "reason_codes": ["NO_COMPLETE_PROPOSITION_WITH_CANDIDATES"],
                }
            else:
                terminals[span_id] = {
                    "status": "NO_COMPLETE_PROPOSITION",
                    "reason_codes": [],
                }
            continue
        if not raw_candidates:
            terminals[span_id] = {
                "status": "PENDING_ROOT_PROTOCOL_INVALID",
                "reason_codes": ["PROPOSITIONS_TERMINAL_WITHOUT_CANDIDATES"],
            }
            continue
        accepted_for_span = 0
        rejected_for_span = 0
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, Mapping):
                rejected_for_span += 1
                rejected.append({
                    "source_span_id": span_id,
                    "validator_verdict": "REJECTED_PROTOCOL",
                    "validator_reason_codes": ["COMPACT_PROPOSITION_NOT_OBJECT"],
                    "protocol_attempt": attempt,
                })
                continue
            materialized, errors, unit_ids = _compact_candidate_materialization(
                raw_candidate,
                span_id=span_id,
                span=spans_by_id[span_id],
                units_by_id=units_by_id,
            )
            if errors or materialized is None:
                rejected_for_span += 1
                rejected.append({
                    "source_span_id": span_id,
                    "validator_verdict": "REJECTED_PROTOCOL",
                    "validator_reason_codes": errors,
                    "protocol_attempt": attempt,
                })
                continue
            local, materialization_errors = _materialize_candidate_offsets(
                materialized,
                spans_by_id[span_id],
            )
            if materialization_errors:
                rejected_for_span += 1
                rejected.append({
                    "source_span_id": span_id,
                    "validator_verdict": "REJECTED_PROVENANCE",
                    "validator_reason_codes": materialization_errors,
                    "protocol_attempt": attempt,
                })
                continue
            validated = validate_proposition_candidate(
                local,
                spans_by_id,
                document_version_hash=document_version_hash,
                model_id=proposition_model_id(),
                prompt_revision=PROPOSITION_PROMPT_REVISION,
                extraction_run_id=extraction_run_id,
            )
            validated["protocol_attempt"] = attempt
            if _text(validated.get("validator_verdict")).startswith("REJECTED"):
                rejected_for_span += 1
                rejected.append(validated)
                continue
            validated["source_unit_ids"] = unit_ids
            accepted_for_span += 1
            accepted.append(validated)
        terminals[span_id] = {
            "status": (
                "PROCESSED_WITH_REJECTIONS"
                if accepted_for_span and rejected_for_span
                else "PROCESSED"
                if accepted_for_span
                else "PENDING_ROOT_PROTOCOL_INVALID"
            ),
            "reason_codes": (
                ["COMPACT_PROPOSITION_CANDIDATE_REJECTIONS"]
                if accepted_for_span and rejected_for_span
                else ["COMPACT_PROPOSITION_NO_VALID_CANDIDATE"]
                if not accepted_for_span
                else []
            ),
        }
    return accepted, rejected, terminals, True


def _repair_prompt(
    batch: list[dict[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> str:
    payload = _prompt_payload(batch)
    return (
        "Repair only the supplied target spans that lack a valid terminal response. Return one and only one "
        "record per target, and finish each record before starting the next target. Emit status first. Use only "
        "the supplied evidence_unit_ids. Do not return source quotes, offsets, metadata, or spans outside this "
        "repair request. A span with no complete proposition must return NO_COMPLETE_PROPOSITION with an empty "
        "propositions array. A PROPOSITIONS record must contain at least one complete proposition.\n"
        f"Validator diagnostics: {json.dumps(dict(diagnostics), ensure_ascii=False, separators=(',', ':'))}\n"
        "Return exactly {\"spans\":[{\"span_id\":\"...\",\"status\":\"PROPOSITIONS|NO_COMPLETE_PROPOSITION\","
        "\"propositions\":[{\"evidence_unit_ids\":[\"unit_...\"],\"statement\":\"...\","
        "\"attribution\":\"CURRENT_AUTHORS|CITED_WORK|BACKGROUND|UNSPECIFIED\","
        "\"polarity\":\"POSITIVE|NEGATIVE|MIXED|UNSPECIFIED\","
        "\"modality\":\"ASSERTED|SUGGESTIVE|CONDITIONAL|UNSPECIFIED\","
        "\"completeness\":\"COMPLETE_PROPOSITION|CONTEXT_ONLY|FRAGMENT|METHOD_DESCRIPTION|AUTHOR_LIMITATION\","
        "\"scope\":\"LOCAL_FINDING|SECTION_SYNTHESIS|FULL_DOCUMENT_CONCLUSION\","
        "\"meta\":{\"quantities\":[],\"boundaries\":[],\"limitations\":[]}}]}]}\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _coverage_report(
    spans: list[dict[str, Any]],
    coverage_manifest: list[dict[str, Any]],
    *,
    propositions: list[dict[str, Any]],
    unresolved_composition_count: int,
) -> dict[str, Any]:
    eligible_ids = {
        _text(item.get("source_span_id")) for item in spans if item.get("extraction_eligible") is True
    }
    processed_ids = {
        _text(item.get("source_span_id"))
        for item in coverage_manifest
        if item.get("status") in _PROCESSED_COVERAGE_STATUSES
    }
    failed_batch_ids = sorted({
        _text(item.get("batch_id"))
        for item in coverage_manifest
        if item.get("status") not in _PROCESSED_COVERAGE_STATUSES
        and _text(item.get("batch_id"))
    })
    eligible_sections = {
        _text(item.get("section_id")) for item in spans if item.get("extraction_eligible") is True
    }
    processed_sections = {
        _text(item.get("section_id"))
        for item in spans
        if _text(item.get("source_span_id")) in processed_ids
    }
    status = "PASS" if eligible_ids == processed_ids and not failed_batch_ids else "PARTIAL"
    return {
        "schema_version": PROPOSITION_COVERAGE_REPORT_VERSION,
        "eligible_section_count": len(eligible_sections),
        "processed_section_count": len(processed_sections),
        "eligible_span_count": len(eligible_ids),
        "processed_span_count": len(processed_ids),
        "failed_batch_ids": failed_batch_ids,
        "author_result_section_coverage": sum(
            1 for item in propositions
            if item.get("proposition_type") == "AUTHOR_FINDING"
        ),
        "quantitative_statement_coverage": sum(
            1 for item in propositions if item.get("quantities")
        ),
        "limitation_section_coverage": sum(
            1 for item in propositions
            if item.get("proposition_type") == "LIMITATION"
        ),
        "unresolved_composition_count": unresolved_composition_count,
        "status": status,
    }


def _resumable_prior_artifact(
    value: Mapping[str, Any] | None,
    *,
    document_version_hash: str,
    policy: ScienceExecutionPolicy,
) -> dict[str, Any] | None:
    source = value if isinstance(value, Mapping) else {}
    if any((
        source.get("schema_version") != PROPOSITION_EXTRACTION_SCHEMA_VERSION,
        _text(source.get("document_version_hash")) != document_version_hash,
        _text(source.get("prompt_revision")) != PROPOSITION_PROMPT_REVISION,
        _text(source.get("evidence_unit_registry_revision"))
        != EVIDENCE_UNIT_REGISTRY_REVISION,
        _text(source.get("composition_prompt_revision"))
        != PROPOSITION_COMPOSITION_PROMPT_REVISION,
        _text(source.get("model_id")) != proposition_model_id(),
        _text(source.get("policy_schema_version")) != policy.schema_version,
        source.get("effective_use_llm") is not policy.use_llm,
        dict(source.get("effective_policy") or {}) != policy.to_dict(),
    )):
        return None
    return dict(source)


def extract_document_propositions(
    span_set: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    prior_artifact: Mapping[str, Any] | None = None,
    prior_batch_artifacts: Iterable[Mapping[str, Any]] | None = None,
    batch_checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    document = span_set.get("document") if isinstance(span_set.get("document"), Mapping) else {}
    document_version_hash = _text(document.get("document_version_hash"))
    all_eligible_spans = [
        dict(item) for item in span_set.get("source_spans", [])
        if isinstance(item, Mapping) and item.get("extraction_eligible") is True
    ]
    requested_review_ids = {
        _text(item)
        for item in span_set.get("review_source_span_ids", [])
        if _text(item)
    }
    spans = [
        span for span in all_eligible_spans
        if not requested_review_ids
        or _text(span.get("source_span_id")) in requested_review_ids
    ]
    coverage_by_id = {
        _text(item.get("source_span_id")): dict(item)
        for item in span_set.get("coverage_manifest", [])
        if isinstance(item, Mapping) and _text(item.get("source_span_id"))
    }
    current_span_ids = {
        _text(item.get("source_span_id"))
        for item in spans
        if _text(item.get("source_span_id"))
    }
    review_source_span_ids = sorted(current_span_ids)
    coverage_by_id = {
        span_id: item
        for span_id, item in coverage_by_id.items()
        if span_id in current_span_ids
    }
    review_selection = (
        dict(span_set.get("review_selection"))
        if isinstance(span_set.get("review_selection"), Mapping)
        else {}
    )
    expected_source_span_cache_keys = {
        _text(span.get("source_span_id")): _source_span_cache_key(
            span,
            document_version_hash=document_version_hash,
        )
        for span in spans
        if _text(span.get("source_span_id"))
    }
    prior = _resumable_prior_artifact(
        prior_artifact,
        document_version_hash=document_version_hash,
        policy=policy,
    )
    if prior is not None:
        coverage_by_id.update({
            _text(item.get("source_span_id")): dict(item)
            for item in prior.get("coverage_manifest", [])
            if isinstance(item, Mapping)
            and _text(item.get("source_span_id")) in current_span_ids
            and _text(item.get("source_span_cache_key"))
            == expected_source_span_cache_keys.get(_text(item.get("source_span_id")))
        })
    policy_identity = json.dumps(
        policy.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    extraction_run_id = "extract_" + uuid5(
        NAMESPACE_URL,
        "|".join((
            document_version_hash,
            PROPOSITION_PROMPT_REVISION,
            PROPOSITION_COMPOSITION_PROMPT_REVISION,
            proposition_model_id(),
            policy_identity,
        )),
    ).hex[:24]
    input_status = _text(span_set.get("status"))
    if input_status != "STRUCTURED":
        blocking_status = (
            input_status
            if input_status in {
                "REEXTRACTION_REQUIRED",
                "SPAN_STRUCTURE_REPAIR_REQUIRED",
                "SECTION_STRUCTURE_PENDING",
                "TEXT_INTEGRITY_FAILED",
                "SOURCE_LOCATORS_INCOMPLETE",
                "NEEDS_OCR",
                "DOCUMENT_INGESTION_FAILED",
            }
            else "PROPOSITION_INPUT_NOT_READY"
        )
        blocking_reason = (
            "PROPOSITION_SOURCE_STRUCTURE_NOT_READY"
            if input_status else "PROPOSITION_SOURCE_STATUS_MISSING"
        )
        for span in spans:
            coverage_by_id[span["source_span_id"]] = {
                **coverage_by_id.get(span["source_span_id"], {}),
                "source_span_id": span["source_span_id"],
                "source_span_cache_key": expected_source_span_cache_keys[
                    span["source_span_id"]
                ],
                "section_id": span.get("section_id"),
                "section_heading": span.get("section_heading"),
                "section_disposition": span.get("section_disposition"),
                "status": "BLOCKED",
                "batch_id": "preflight",
                "reason_codes": [blocking_reason],
            }
        coverage_manifest = list(coverage_by_id.values())
        return {
            "schema_version": PROPOSITION_EXTRACTION_SCHEMA_VERSION,
            "artifact_id": extraction_run_id,
            "document_version_id": _text(document.get("document_version_id")),
            "document_version_hash": document_version_hash,
            "extraction_run_id": extraction_run_id,
            "prompt_revision": PROPOSITION_PROMPT_REVISION,
            "evidence_unit_registry_revision": EVIDENCE_UNIT_REGISTRY_REVISION,
            "composition_prompt_revision": PROPOSITION_COMPOSITION_PROMPT_REVISION,
            "model_id": proposition_model_id(),
            "policy_schema_version": policy.schema_version,
            "effective_use_llm": policy.use_llm,
            "effective_policy": policy.to_dict(),
            "status": blocking_status,
            "reason_codes": list(dict.fromkeys([
                *list(span_set.get("reason_codes") or []),
                blocking_reason,
            ])),
            "proposition_extraction_status": "PARTIAL",
            "semantic_entailment_status": "PENDING",
            "composition_status": "PENDING",
            "coverage_status": "PARTIAL",
            "atomic_candidates_raw": [],
            "atomic_batch_artifacts": [],
            "propositions": [],
            "assertion_candidates": [],
            "rejected_candidates": [],
            "coverage_manifest": coverage_manifest,
            "review_source_span_ids": review_source_span_ids,
            "review_selection": review_selection,
            "coverage_report": _coverage_report(
                spans,
                coverage_manifest,
                propositions=[],
                unresolved_composition_count=0,
            ),
        }
    if not policy.use_llm or policy.assertion_extraction_mode != "llm_primary":
        for span in spans:
            coverage_by_id[span["source_span_id"]] = {
                **coverage_by_id.get(span["source_span_id"], {}),
                "source_span_cache_key": expected_source_span_cache_keys[
                    span["source_span_id"]
                ],
                "status": "SKIPPED",
                "reason_codes": ["LLM_EXTRACTION_DISABLED"],
            }
        coverage_manifest = list(coverage_by_id.values())
        return {
            "schema_version": PROPOSITION_EXTRACTION_SCHEMA_VERSION,
            "artifact_id": extraction_run_id,
            "document_version_id": _text(document.get("document_version_id")),
            "document_version_hash": document_version_hash,
            "extraction_run_id": extraction_run_id,
            "prompt_revision": PROPOSITION_PROMPT_REVISION,
            "evidence_unit_registry_revision": EVIDENCE_UNIT_REGISTRY_REVISION,
            "composition_prompt_revision": PROPOSITION_COMPOSITION_PROMPT_REVISION,
            "model_id": proposition_model_id(),
            "policy_schema_version": policy.schema_version,
            "effective_use_llm": policy.use_llm,
            "effective_policy": policy.to_dict(),
            "status": "LLM_DISABLED",
            "reason_codes": ["LLM_EXTRACTION_DISABLED"],
            "proposition_extraction_status": "PARTIAL",
            "semantic_entailment_status": "PENDING",
            "composition_status": "PENDING",
            "coverage_status": "PARTIAL",
            "atomic_candidates_raw": [],
            "atomic_batch_artifacts": [],
            "propositions": [],
            "assertion_candidates": [],
            "rejected_candidates": [],
            "coverage_manifest": coverage_manifest,
            "review_source_span_ids": review_source_span_ids,
            "review_selection": review_selection,
            "coverage_report": _coverage_report(
                spans, coverage_manifest, propositions=[], unresolved_composition_count=0
            ),
        }
    call = llm_call or _default_llm_call
    spans_by_id = {span["source_span_id"]: span for span in spans}
    units_by_id = _evidence_unit_registry(spans)
    propositions: list[dict[str, Any]] = [
        dict(item)
        for item in (prior or {}).get("atomic_candidates_raw", [])
        if isinstance(item, Mapping)
        and _text(item.get("source_span_id")) in spans_by_id
        and coverage_by_id.get(_text(item.get("source_span_id")), {}).get("status")
        in _PROCESSED_COVERAGE_STATUSES
    ]
    rejected: list[dict[str, Any]] = [
        dict(item)
        for item in (prior or {}).get("rejected_candidates", [])
        if isinstance(item, Mapping)
    ]
    transient_prefixes = (
        "LLM_PROPOSITION_BATCH_FAILED:",
        "LLM_PROPOSITION_SCHEMA_INVALID:",
        "LLM_PROPOSITION_PROTOCOL_INVALID:",
        "LLM_PROPOSITION_PROTOCOL_REPAIR_FAILED:",
        "LLM_PROPOSITION_COMPOSITION_PENDING:",
        "LLM_PROPOSITION_COMPOSITION_PROTOCOL_INVALID:",
    )
    reason_codes = [
        str(item)
        for item in [
            *list(span_set.get("reason_codes") or []),
            *list((prior or {}).get("reason_codes") or []),
        ]
        if str(item) and not str(item).startswith(transient_prefixes)
    ]
    batch_artifacts_by_id = {
        _text(item.get("batch_id")): dict(item)
        for item in (prior or {}).get("atomic_batch_artifacts", [])
        if isinstance(item, Mapping) and _text(item.get("batch_id"))
    }
    for item in prior_batch_artifacts or []:
        if not isinstance(item, Mapping):
            continue
        if any((
            _text(item.get("schema_version")) != "atomic_proposition_batch_v1",
            _text(item.get("document_version_hash")) != document_version_hash,
            _text(item.get("prompt_revision")) != PROPOSITION_PROMPT_REVISION,
            _text(item.get("evidence_unit_registry_revision"))
            != EVIDENCE_UNIT_REGISTRY_REVISION,
            _text(item.get("composition_prompt_revision"))
            != PROPOSITION_COMPOSITION_PROMPT_REVISION,
            _text(item.get("model_id")) != proposition_model_id(),
            _text(item.get("policy_schema_version")) != policy.schema_version,
            item.get("effective_use_llm") is not policy.use_llm,
            dict(item.get("effective_policy") or {}) != policy.to_dict(),
        )):
            continue
        batch_id = _text(item.get("batch_id"))
        if not batch_id:
            continue
        batch_artifacts_by_id[batch_id] = dict(item)
        for coverage in item.get("coverage_terminal_states", []):
            if not isinstance(coverage, Mapping):
                continue
            span_id = _text(coverage.get("source_span_id"))
            if (
                span_id in current_span_ids
                and _text(coverage.get("source_span_cache_key"))
                == expected_source_span_cache_keys.get(span_id)
            ):
                coverage_by_id[span_id] = dict(coverage)
        for proposition in item.get("atomic_candidates_raw", []):
            if not isinstance(proposition, Mapping):
                continue
            span_id = _text(proposition.get("source_span_id"))
            if (
                span_id in current_span_ids
                and coverage_by_id.get(span_id, {}).get("status")
                in _PROCESSED_COVERAGE_STATUSES
            ):
                propositions.append(dict(proposition))
        for rejected_candidate in item.get("rejected_candidates", []):
            if isinstance(rejected_candidate, Mapping):
                rejected.append(dict(rejected_candidate))
    candidate_id = _text(document.get("paper_id")) or document_version_hash

    def extract_batch(
        batch_index: int,
        batch_id: str,
        batch: list[dict[str, Any]],
    ) -> dict[str, Any]:
        local_reason_codes: list[str] = []
        local_rejected: list[dict[str, Any]] = []
        coverage_updates: dict[str, dict[str, Any]] = {}
        response_diagnostics: dict[str, Any] = {}
        pending_status = ""
        batch_span_order = [span["source_span_id"] for span in batch]
        batch_span_ids = set(batch_span_order)
        prompt = _prompt(batch)
        batch_max_tokens = _batch_max_tokens(batch)

        def coverage_update(
            span_id: str,
            *,
            status: str,
            reason_codes: Iterable[str] = (),
        ) -> dict[str, Any]:
            span = spans_by_id[span_id]
            return {
                **coverage_by_id.get(span_id, {}),
                "source_span_id": span_id,
                "source_span_cache_key": expected_source_span_cache_keys[span_id],
                "section_id": span.get("section_id"),
                "section_heading": span.get("section_heading"),
                "section_disposition": span.get("section_disposition"),
                "status": status,
                "batch_id": batch_id,
                "reason_codes": list(dict.fromkeys(reason_codes)),
            }

        try:
            response = run_science_llm_job(
                LLMJob(
                    candidate_id=candidate_id,
                    stage="proposition_batch",
                    batch_id=batch_id,
                    prompt_chars=len(prompt),
                    max_tokens=batch_max_tokens,
                    input_span_count=len(batch),
                    candidate_max_inflight=SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT,
                ),
                lambda: call(
                    system=(
                        "You extract source-grounded scientific propositions. Return valid JSON only. "
                        "Never invent a subject, predicate, object, number, attribution, or source quote."
                    ),
                    prompt=prompt,
                    max_tokens=batch_max_tokens,
                    required_list_key="spans",
                    protocol_name="PROPOSITION_COMPACT",
                ),
            )
            payload, response_diagnostics = _unwrap_llm_response(
                response,
                required_list_key="spans",
            )
        except Exception as exc:
            exception_diagnostics = getattr(exc, "diagnostics", None)
            if isinstance(exception_diagnostics, dict):
                response_diagnostics = dict(exception_diagnostics)
            pending_status, pending_reason = _pending_status_for_error(exc)
            local_reason_codes.append(
                f"{pending_reason}:{batch_id}:{type(exc).__name__}"
            )
            if pending_status == "PENDING_TRANSPORT":
                log_event(
                    "WARN",
                    "proposition_protocol_failed",
                    protocol="PROPOSITION_COMPACT",
                    batch_id=batch_id,
                    status=pending_status,
                    response_chars=response_diagnostics.get("response_chars", 0),
                    finish_reason=response_diagnostics.get("finish_reason", ""),
                    response_truncated=response_diagnostics.get("response_truncated", False),
                    root_object_unbalanced=response_diagnostics.get("root_object_unbalanced", False),
                    recovery_mode=response_diagnostics.get("recovery_mode", ""),
                    top_level_keys=response_diagnostics.get("top_level_keys", []),
                    error_message=response_diagnostics.get("error_message", ""),
                    provider_code=response_diagnostics.get("provider_code", ""),
                    request_id=response_diagnostics.get("request_id", ""),
                    response_preview=response_diagnostics.get("response_preview", ""),
                    expected_root_key="spans",
                    unresolved_span_count=len(batch),
                    repair_span_count=len(batch),
                )
                for span in batch:
                    span_id = span["source_span_id"]
                    coverage_updates[span_id] = coverage_update(
                        span_id,
                        status=pending_status,
                        reason_codes=[pending_reason],
                    )
                return {
                    "batch_index": batch_index,
                    "batch_id": batch_id,
                    "batch_span_ids": batch_span_ids,
                    "propositions": [],
                    "rejected": [],
                    "reason_codes": local_reason_codes,
                    "coverage_updates": coverage_updates,
                    "diagnostics": response_diagnostics,
                }
            initial_accepted = []
            initial_rejected = [{
                "validator_verdict": "PENDING_PROTOCOL",
                "validator_reason_codes": [pending_reason],
                "protocol_attempt": "INITIAL",
            }]
            initial_terminals = {
                span_id: {"status": pending_status, "reason_codes": [pending_reason]}
                for span_id in batch_span_ids
            }
            root_valid = False
        else:
            initial_accepted, initial_rejected, initial_terminals, root_valid = (
                _validate_compact_batch(
                    payload,
                    batch_span_ids=batch_span_ids,
                    spans_by_id=spans_by_id,
                    units_by_id=units_by_id,
                    document_version_hash=document_version_hash,
                    extraction_run_id=extraction_run_id,
                    attempt="INITIAL",
                )
            )
        local_rejected.extend(initial_rejected)
        terminal_statuses = {
            "PROCESSED",
            "PROCESSED_WITH_REJECTIONS",
            "NO_COMPLETE_PROPOSITION",
        }
        unresolved_span_ids = {
            span_id
            for span_id in batch_span_ids
            if _text(initial_terminals.get(span_id, {}).get("status"))
            not in terminal_statuses
        }
        if pending_status or response_diagnostics.get("response_truncated"):
            log_event(
                "WARN",
                "proposition_protocol_failed",
                protocol="PROPOSITION_COMPACT",
                batch_id=batch_id,
                status=pending_status or "PENDING_RESPONSE_TRUNCATED",
                response_chars=response_diagnostics.get("response_chars", 0),
                finish_reason=response_diagnostics.get("finish_reason", ""),
                response_truncated=response_diagnostics.get("response_truncated", False),
                root_object_unbalanced=response_diagnostics.get("root_object_unbalanced", False),
                recovery_mode=response_diagnostics.get("recovery_mode", ""),
                top_level_keys=response_diagnostics.get("top_level_keys", []),
                error_message=response_diagnostics.get("error_message", ""),
                provider_code=response_diagnostics.get("provider_code", ""),
                request_id=response_diagnostics.get("request_id", ""),
                response_preview=response_diagnostics.get("response_preview", ""),
                expected_root_key="spans",
                unresolved_span_count=len(unresolved_span_ids),
                repair_span_count=len(unresolved_span_ids),
            )
        accepted = list(initial_accepted)
        final_terminals = dict(initial_terminals)
        repair_error_status = ""
        repair_error_reason = ""
        if unresolved_span_ids:
            repair_diagnostics = {
                span_id: dict(initial_terminals.get(span_id) or {
                    "status": "PENDING_ROOT_PROTOCOL_INVALID",
                    "reason_codes": [
                        "COMPACT_SPAN_ROOT_INVALID"
                        if not root_valid else "COMPACT_SPAN_RESPONSE_MISSING"
                    ],
                })
                for span_id in unresolved_span_ids
            }
            unresolved_spans = [
                span for span in batch
                if span["source_span_id"] in unresolved_span_ids
            ]
            for repair_index in range(0, len(unresolved_spans), REPAIR_MAX_SPANS):
                repair_batch = unresolved_spans[repair_index:repair_index + REPAIR_MAX_SPANS]
                repair_span_ids = {_text(span.get("source_span_id")) for span in repair_batch}
                repair_batch_id = f"{batch_id}_repair_{repair_index // REPAIR_MAX_SPANS + 1:04d}"
                repair_prompt = _repair_prompt(
                    repair_batch,
                    {span_id: repair_diagnostics[span_id] for span_id in repair_span_ids},
                )
                repair_max_tokens = min(4000, 700 + len(repair_batch) * 450)
                try:
                    repair_response = run_science_llm_job(
                        LLMJob(
                            candidate_id=candidate_id,
                            stage="proposition_batch_repair",
                            batch_id=repair_batch_id,
                            prompt_chars=len(repair_prompt),
                            max_tokens=repair_max_tokens,
                            input_span_count=len(repair_batch),
                            candidate_max_inflight=SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT,
                        ),
                        lambda: call(
                            system=(
                                "Repair compact source-grounded proposition span terminals. Return valid JSON only; "
                                "use only supplied evidence-unit ids and do not emit quotes or offsets."
                            ),
                            prompt=repair_prompt,
                            max_tokens=repair_max_tokens,
                            required_list_key="spans",
                            protocol_name="PROPOSITION_COMPACT_REPAIR",
                        ),
                    )
                    repair_payload, repair_response_diagnostics = _unwrap_llm_response(
                        repair_response,
                        required_list_key="spans",
                    )
                    response_diagnostics.update({
                        "repair_last": repair_response_diagnostics,
                    })
                except Exception as exc:
                    exception_diagnostics = getattr(exc, "diagnostics", None)
                    if isinstance(exception_diagnostics, dict):
                        response_diagnostics.update({"repair_last": dict(exception_diagnostics)})
                    repair_error_status, repair_error_reason = _pending_status_for_error(exc)
                    local_reason_codes.append(
                        f"{repair_error_reason}:{repair_batch_id}:{type(exc).__name__}"
                    )
                    final_terminals.update({
                        span_id: {
                            "status": repair_error_status,
                            "reason_codes": [repair_error_reason],
                        }
                        for span_id in repair_span_ids
                    })
                    continue
                repair_accepted, repair_rejected, repair_terminals, _ = (
                    _validate_compact_batch(
                        repair_payload,
                        batch_span_ids=repair_span_ids,
                        spans_by_id=spans_by_id,
                        units_by_id=units_by_id,
                        document_version_hash=document_version_hash,
                        extraction_run_id=extraction_run_id,
                        attempt="REPAIR",
                    )
                )
                accepted.extend(repair_accepted)
                local_rejected.extend(repair_rejected)
                final_terminals.update(repair_terminals)
        accepted_span_ids = {
            _text(item.get("source_span_id")) for item in accepted
        }
        rejected_span_ids = {
            _text(item.get("source_span_id"))
            for item in local_rejected
            if _text(item.get("source_span_id")) in batch_span_ids
        }
        for span_id in batch_span_order:
            terminal = final_terminals.get(span_id) or {}
            terminal_status = _text(terminal.get("status"))
            terminal_reasons = list(terminal.get("reason_codes") or [])
            if terminal_status in terminal_statuses:
                coverage_status = terminal_status
                if span_id in accepted_span_ids and span_id in rejected_span_ids:
                    coverage_status = "PROCESSED_WITH_REJECTIONS"
                coverage_updates[span_id] = coverage_update(
                    span_id,
                    status=coverage_status,
                    reason_codes=terminal_reasons,
                )
                continue
            if terminal_status in _PENDING_COVERAGE_STATUSES:
                coverage_updates[span_id] = coverage_update(
                    span_id,
                    status=terminal_status,
                    reason_codes=terminal_reasons,
                )
                continue
            coverage_updates[span_id] = coverage_update(
                span_id,
                status="PENDING_ROOT_PROTOCOL_INVALID",
                reason_codes=[
                    "LLM_PROPOSITION_PROTOCOL_INVALID",
                    *terminal_reasons,
                ],
            )
        if any(item.get("status") == "PENDING_ROOT_PROTOCOL_INVALID" for item in coverage_updates.values()):
            local_reason_codes.append(f"LLM_PROPOSITION_PROTOCOL_INVALID:{batch_id}")
        return {
            "batch_index": batch_index,
            "batch_id": batch_id,
            "batch_span_ids": batch_span_ids,
            "propositions": accepted,
            "rejected": local_rejected,
            "reason_codes": local_reason_codes,
            "coverage_updates": coverage_updates,
            "diagnostics": response_diagnostics,
        }

    batch_tasks: list[tuple[int, str, list[dict[str, Any]]]] = []
    for batch_index, scheduled_batch in enumerate(_batches(spans)):
        batch = [
            span
            for span in scheduled_batch
            if coverage_by_id.get(span["source_span_id"], {}).get("status")
            not in _PROCESSED_COVERAGE_STATUSES
        ]
        if batch:
            batch_tasks.append(
                (batch_index, f"batch_{batch_index + 1:04d}", batch)
            )

    batch_results: dict[int, dict[str, Any]] = {}
    batch_workers = min(
        SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT,
        len(batch_tasks),
    )
    if batch_workers == 1:
        batch_index, batch_id, batch = batch_tasks[0]
        batch_results[batch_index] = extract_batch(batch_index, batch_id, batch)
    elif batch_workers > 1:
        with ThreadPoolExecutor(max_workers=batch_workers) as executor:
            futures = {
                executor.submit(extract_batch, batch_index, batch_id, batch): (
                    batch_index,
                    batch_id,
                    batch,
                )
                for batch_index, batch_id, batch in batch_tasks
            }
            for future in as_completed(futures):
                batch_index, batch_id, batch = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    pending_status, pending_reason = _pending_status_for_error(exc)
                    result = {
                        "batch_index": batch_index,
                        "batch_id": batch_id,
                        "batch_span_ids": {
                            span["source_span_id"] for span in batch
                        },
                        "propositions": [],
                        "rejected": [],
                        "reason_codes": [f"{pending_reason}:{batch_id}:{type(exc).__name__}"],
                        "diagnostics": dict(getattr(exc, "diagnostics", {}) or {}),
                        "coverage_updates": {
                            span["source_span_id"]: {
                                **coverage_by_id.get(span["source_span_id"], {}),
                                "source_span_id": span["source_span_id"],
                                "section_id": span.get("section_id"),
                                "section_heading": span.get("section_heading"),
                                "section_disposition": span.get("section_disposition"),
                                "status": pending_status,
                                "batch_id": batch_id,
                                "reason_codes": [pending_reason],
                            }
                            for span in batch
                        },
                    }
                batch_results[batch_index] = result

    for batch_index in sorted(batch_results):
        result = batch_results[batch_index]
        batch_span_ids = set(result.get("batch_span_ids") or set())
        propositions = [
            proposition
            for proposition in propositions
            if _text(proposition.get("source_span_id")) not in batch_span_ids
        ]
        propositions.extend(result.get("propositions") or [])
        rejected.extend(result.get("rejected") or [])
        reason_codes.extend(result.get("reason_codes") or [])
        coverage_by_id.update(result.get("coverage_updates") or {})
        batch_artifact = {
            "schema_version": "atomic_proposition_batch_v1",
            "document_version_id": _text(document.get("document_version_id")),
            "document_version_hash": document_version_hash,
            "artifact_id": extraction_run_id,
            "prompt_revision": PROPOSITION_PROMPT_REVISION,
            "composition_prompt_revision": PROPOSITION_COMPOSITION_PROMPT_REVISION,
            "model_id": proposition_model_id(),
            "policy_schema_version": policy.schema_version,
            "effective_use_llm": policy.use_llm,
            "effective_policy": policy.to_dict(),
            "evidence_unit_registry_revision": EVIDENCE_UNIT_REGISTRY_REVISION,
            "batch_id": _text(result.get("batch_id")),
            "source_span_ids": sorted(batch_span_ids),
            "source_units": [
                {
                    "unit_id": _text(unit.get("unit_id")),
                    "source_span_id": _text(unit.get("source_span_id")),
                    "quote_char_start": unit.get("quote_char_start"),
                    "quote_char_end": unit.get("quote_char_end"),
                }
                for unit in units_by_id.values()
                if _text(unit.get("source_span_id")) in batch_span_ids
            ],
            "atomic_candidates_raw": [
                dict(item)
                for item in result.get("propositions", [])
                if isinstance(item, Mapping)
            ],
            "rejected_candidates": [
                dict(item)
                for item in result.get("rejected", [])
                if isinstance(item, Mapping)
            ],
            "proposition_ids": [
                _text(item.get("proposition_id"))
                for item in result.get("propositions", [])
                if isinstance(item, Mapping) and _text(item.get("proposition_id"))
            ],
            "rejected_candidate_count": len(result.get("rejected") or []),
            "coverage_terminal_states": [
                dict(item)
                for item in (result.get("coverage_updates") or {}).values()
                if isinstance(item, Mapping)
            ],
            "response_diagnostics": dict(result.get("diagnostics") or {}),
            "response_chars": int((result.get("diagnostics") or {}).get("response_chars") or 0),
            "finish_reason": _text((result.get("diagnostics") or {}).get("finish_reason")),
            "provider_code": _text((result.get("diagnostics") or {}).get("provider_code")),
            "request_id": _text((result.get("diagnostics") or {}).get("request_id")),
            "error_message": _text((result.get("diagnostics") or {}).get("error_message")),
            "response_preview": _text((result.get("diagnostics") or {}).get("response_preview")),
            "response_truncated": bool((result.get("diagnostics") or {}).get("response_truncated")),
            "safe_partial_recovery": bool((result.get("diagnostics") or {}).get("safe_partial_recovery")),
            "root_object_unbalanced": bool((result.get("diagnostics") or {}).get("root_object_unbalanced")),
            "recovery_mode": _text((result.get("diagnostics") or {}).get("recovery_mode")),
            "top_level_keys": list((result.get("diagnostics") or {}).get("top_level_keys") or []),
            "expected_root_key": _text((result.get("diagnostics") or {}).get("required_list_key")) or "spans",
            "unresolved_span_count": sum(
                1 for item in (result.get("coverage_updates") or {}).values()
                if _text(item.get("status")) not in _TERMINAL_BATCH_STATUSES
            ),
            "repair_span_count": sum(
                1 for item in (result.get("coverage_updates") or {}).values()
                if _text(item.get("status")) in _PENDING_COVERAGE_STATUSES
            ),
            "reason_codes": list(result.get("reason_codes") or []),
        }
        batch_artifacts_by_id[_text(result.get("batch_id"))] = batch_artifact
        if batch_checkpoint is not None:
            try:
                batch_checkpoint(dict(batch_artifact))
            except Exception as exc:
                reason_codes.append(
                    "ATOMIC_BATCH_CHECKPOINT_FAILED:"
                    f"{_text(result.get('batch_id'))}:{type(exc).__name__}"
                )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for proposition in propositions:
        proposition_id = _text(proposition.get("proposition_id"))
        if proposition_id and proposition_id not in seen:
            seen.add(proposition_id)
            deduped.append(proposition)
    composition_candidates = [
        proposition
        for proposition in deduped
        if (
            _text(proposition.get("claim_completeness")).upper()
            in {"CONTEXT_ONLY", "FRAGMENT", "INCOMPLETE_COMPONENT"}
            or _text(proposition.get("polarity")).upper() == "NEGATIVE"
            or _text(proposition.get("claim_scope")).upper()
            == "FULL_DOCUMENT_CONCLUSION"
        )
    ]
    scientific, composition_errors, unresolved_composition_count, rejected_compositions = (
        _compose_document_propositions(
            deduped,
            llm_call=call,
            composition_candidates=composition_candidates,
        )
        if deduped
        else ([], [], 0, [])
    )
    rejected.extend(rejected_compositions)
    reason_codes.extend(composition_errors)
    if composition_errors and unresolved_composition_count == 0:
        reason_codes.append("COMPOSITION_COMPLETED_WITH_REJECTIONS")
    coverage_manifest = list(coverage_by_id.values())
    coverage_report = _coverage_report(
        spans,
        coverage_manifest,
        propositions=scientific,
        unresolved_composition_count=unresolved_composition_count,
    )
    coverage_complete = _text(coverage_report.get("status")) == "PASS"
    proposition_extraction_status = "READY" if coverage_complete else "PARTIAL"
    composition_status = "PENDING" if unresolved_composition_count > 0 else "COMPLETE"
    coverage_status = _text(coverage_report.get("status")) or "PARTIAL"
    status = (
        "PROPOSITION_PARTIAL"
        if proposition_extraction_status == "PARTIAL"
        else "PROPOSITION_READY"
    )
    for proposition in scientific:
        proposition["document_extraction_status"] = status
        proposition["counts_toward_gate"] = False
        proposition["direct_slot_eligible"] = False
    assertion_candidates = _source_bound_assertion_candidates(scientific)
    return {
        "schema_version": PROPOSITION_EXTRACTION_SCHEMA_VERSION,
        "artifact_id": extraction_run_id,
        "document_version_id": _text(document.get("document_version_id")),
        "document_version_hash": document_version_hash,
        "extraction_run_id": extraction_run_id,
        "prompt_revision": PROPOSITION_PROMPT_REVISION,
        "evidence_unit_registry_revision": EVIDENCE_UNIT_REGISTRY_REVISION,
        "composition_prompt_revision": PROPOSITION_COMPOSITION_PROMPT_REVISION,
        "model_id": proposition_model_id(),
        "policy_schema_version": policy.schema_version,
        "effective_use_llm": policy.use_llm,
        "effective_policy": policy.to_dict(),
        "status": status,
        "reason_codes": sorted(set(reason_codes)),
        "proposition_extraction_status": proposition_extraction_status,
        "semantic_entailment_status": "PASS",
        "composition_status": composition_status,
        "coverage_status": coverage_status,
        "atomic_candidates_raw": deduped,
        "atomic_batch_artifacts": [
            batch_artifacts_by_id[batch_id]
            for batch_id in sorted(batch_artifacts_by_id)
        ],
        "propositions": scientific,
        "assertion_candidates": assertion_candidates,
        "rejected_candidates": rejected,
        "coverage_manifest": coverage_manifest,
        "review_source_span_ids": review_source_span_ids,
        "review_selection": review_selection,
        "coverage_report": coverage_report,
    }
