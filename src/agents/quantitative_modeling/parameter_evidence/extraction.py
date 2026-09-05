"""Strict extraction of parameter candidates from controlled local documents."""

from __future__ import annotations

import json
import hashlib
import inspect
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.parameter_contracts import (
    PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
    ParameterContractError,
    model_blueprint_identity,
    normalize_model_blueprint,
    normalize_parameter_evidence_candidate,
)


_EVIDENCE_RESPONSE = re.compile(
    r"\A\s*<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>\s*(?P<json>\{.*?\})\s*"
    r"</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>\s*\Z",
    re.DOTALL,
)


PARAMETER_EVIDENCE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "parameter_id": {"type": "string"},
                    "mathir_symbol": {"type": "string"},
                    "raw_value": {"type": "string"},
                    "normalized_value": {"type": "number"},
                    "normalized_unit": {"type": "string"},
                    "source_kind": {
                        "type": "string",
                        "enum": [
                            "PRIMARY_MEASUREMENT",
                            "REFERENCE_DATABASE",
                            "REVIEW_REPORTED",
                            "USER_PROVIDED",
                        ],
                    },
                    "evidence_locator": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "document_type": {"type": "string"},
                            "section": {"type": "string"},
                            "table_or_figure": {"type": "string"},
                            "page": {"type": ["integer", "null"]},
                            "quoted_text": {"type": "string"},
                        },
                        "required": ["document_type", "quoted_text"],
                    },
                    "conditions": {"type": "object", "additionalProperties": True},
                    "uncertainty": {"type": "object", "additionalProperties": True},
                    "transformation": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "applied": {"type": "boolean"},
                            "formula": {"type": "string"},
                        },
                        "required": ["applied", "formula"],
                    },
                },
                "required": [
                    "parameter_id",
                    "mathir_symbol",
                    "raw_value",
                    "normalized_value",
                    "normalized_unit",
                    "source_kind",
                    "evidence_locator",
                    "conditions",
                    "uncertainty",
                    "transformation",
                ],
            },
        }
    },
    "required": ["candidates"],
}
PARAMETER_EVIDENCE_PROMPT_VERSION = "targeted-sections-v2"


class ParameterEvidenceExtractionError(RuntimeError):
    """Raised when an extraction cannot be anchored to a local source document."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _call_extraction_llm(
    llm_call: Callable[..., object], prompt: str, *, parameter_count: int = 1
) -> object:
    """Use the dedicated extraction phase when the callback supports it."""

    try:
        signature = inspect.signature(llm_call)
        has_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        supports_phase = "phase" in signature.parameters or has_kwargs
        supports_parameter_count = "parameter_count" in signature.parameters or has_kwargs
    except (TypeError, ValueError):
        supports_phase = False
        supports_parameter_count = False
    if supports_phase:
        kwargs: dict[str, object] = {"phase": "parameter_extraction"}
        if supports_parameter_count:
            kwargs["parameter_count"] = max(1, int(parameter_count))
        return llm_call(prompt, **kwargs)
    return llm_call(prompt)


def _normalized_text(value: object) -> str:
    return " ".join(_text(value).split())


def _bounded_json(value: Mapping[str, object], *, maximum: int = 12_000) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)[:maximum]


def _read_document_pages(path: Path, *, cache_directory: Path | None = None) -> tuple[list[str], int | None]:
    cache_path: Path | None = None
    if cache_directory is not None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        cache_path = cache_directory / f"{digest}.json"
        if cache_path.is_file():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                pages = payload.get("pages")
                page_count = payload.get("page_count")
                if (
                    isinstance(pages, list)
                    and all(isinstance(page, str) for page in pages)
                    and (page_count is None or isinstance(page_count, int))
                ):
                    return list(pages), page_count
            except (OSError, json.JSONDecodeError):
                pass
    suffix = path.suffix.casefold()
    try:
        if suffix in {".txt", ".md", ".csv"}:
            text = path.read_text(encoding="utf-8")
            pages = [text]
            page_count: int | None = None
        elif suffix != ".pdf":
            raise ParameterEvidenceExtractionError("parameter evidence documents must be PDF, TXT, MD, or CSV")
        else:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            page_count = len(reader.pages)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"pages": pages, "page_count": page_count}, ensure_ascii=False),
                encoding="utf-8",
            )
        return pages, page_count
    except ParameterEvidenceExtractionError:
        raise
    except Exception as error:
        raise ParameterEvidenceExtractionError(
            f"cannot extract local parameter evidence text: {type(error).__name__}"
        ) from error


def _read_document_text(
    path: Path,
    *,
    maximum_characters: int,
    cache_directory: Path | None = None,
) -> tuple[str, int | None]:
    pages, page_count = _read_document_pages(path, cache_directory=cache_directory)
    return "\n".join(pages)[:maximum_characters], page_count


_SECTION_WORDS = frozenset(
    {
        "abstract",
        "method",
        "methods",
        "model",
        "models",
        "physical conditions",
        "simulation",
        "setup",
        "parameter",
        "parameters",
        "result",
        "results",
        "discussion",
        "appendix",
        "table",
        "figure",
    }
)


def _term_patterns(request: Mapping[str, object]) -> list[re.Pattern[str]]:
    values = [
        _text(request.get("parameter_id")),
        _text(request.get("mathir_symbol")),
        _text(request.get("meaning")),
        _text(request.get("unit")),
        *(_text(item) for item in request.get("required_conditions") or []),
        *(_text(item) for item in request.get("retrieval_queries") or []),
    ]
    patterns: list[re.Pattern[str]] = []
    seen: set[str] = set()
    identifiers = {
        _text(request.get("parameter_id")).casefold(),
        _text(request.get("mathir_symbol")).casefold(),
    }
    for value in values:
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*|[0-9]+(?:\.[0-9]+)?", value):
            normalized = term.casefold()
            if (len(normalized) < 2 and normalized not in identifiers) or normalized in seen:
                continue
            seen.add(normalized)
            patterns.append(re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE))
    return patterns


def _section_heading(page_text: str) -> str:
    for raw_line in page_text.splitlines():
        line = " ".join(raw_line.split()).strip(" -:")
        if not line or len(line) > 100 or line.endswith((".", ";", ",")):
            continue
        lowered = line.casefold()
        if any(word in lowered for word in _SECTION_WORDS) and len(line.split()) <= 10:
            return line
        if re.match(r"^(?:\d+(?:\.\d+)*[.)]?\s+)?[A-Z][A-Za-z0-9 ,:/()'-]{2,80}$", line):
            return line
    return ""


def _select_relevant_sections(
    *,
    blueprint: Mapping[str, object],
    source_document: Mapping[str, object],
    pages: list[str],
    max_snippets_per_parameter: int = 3,
    context_pages_before: int = 1,
    context_pages_after: int = 1,
    max_snippet_characters: int = 6000,
    minimum_keyword_hits: int = 2,
) -> tuple[str, dict[str, Any]]:
    requests = {
        _text(request.get("parameter_id")): request
        for request in blueprint.get("parameter_requests") or []
        if _text(request.get("parameter_id"))
    }
    requested_ids = {
        _text(value) for value in source_document.get("parameter_request_ids") or [] if _text(value)
    }
    if requested_ids:
        requests = {key: value for key, value in requests.items() if key in requested_ids}
    if not requests:
        return "", {
            "status": "SKIPPED_NO_PARAMETER_EVIDENCE",
            "matched_parameter_ids": [],
            "selected_pages": [],
            "skipped": True,
        }
    selected: dict[int, set[str]] = {}
    matched_ids: set[str] = set()
    for parameter_id, request in requests.items():
        patterns = _term_patterns(request)
        scored: list[tuple[int, int]] = []
        for index, page in enumerate(pages):
            score = sum(len(pattern.findall(page)) for pattern in patterns)
            if score >= max(1, int(minimum_keyword_hits)):
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for _score, page_index in scored[: max(1, int(max_snippets_per_parameter))]:
            matched_ids.add(parameter_id)
            for context_index in range(
                max(0, page_index - max(0, int(context_pages_before))),
                min(len(pages), page_index + max(0, int(context_pages_after)) + 1),
            ):
                selected.setdefault(context_index, set()).add(parameter_id)
    if not selected:
        return "", {
            "status": "SKIPPED_NO_PARAMETER_EVIDENCE",
            "matched_parameter_ids": [],
            "selected_pages": [],
            "skipped": True,
        }
    chunks: list[str] = []
    for page_index in sorted(selected):
        heading = _section_heading(pages[page_index])
        label = f"[page={page_index + 1}]"
        if heading:
            label += f" [section={heading}]"
        chunks.append(label + "\n" + pages[page_index].strip())
    text = "\n\n".join(chunks)
    if len(text) > max_snippet_characters:
        text = text[:max_snippet_characters]
    return text, {
        "status": "EXTRACTED_TARGETED_SECTIONS",
        "matched_parameter_ids": sorted(matched_ids),
        "selected_pages": [index + 1 for index in sorted(selected)],
        "skipped": False,
    }


def _read_cache_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _write_cache_json(path: Path | None, payload: Mapping[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(payload), ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def build_parameter_evidence_extraction_prompt(
    *,
    blueprint: Mapping[str, object],
    source_document: Mapping[str, object],
    document_text: str,
) -> str:
    """Ask the LLM to locate values, never to fabricate a source or choice."""

    requested_ids = {
        _text(value) for value in source_document.get("parameter_request_ids") or [] if _text(value)
    }
    prompt_requests = [
        {
            key: request.get(key)
            for key in (
                "parameter_id",
                "mathir_symbol",
                "meaning",
                "unit",
                "dimension",
                "evidence_requirement",
                "required_conditions",
            )
            if key in request
        }
        for request in blueprint.get("parameter_requests") or []
        if not requested_ids or _text(request.get("parameter_id")) in requested_ids
    ]
    return "\n".join(
        (
            "Extract proposed scalar parameter evidence only from the supplied targeted source sections.",
            "Return exactly one JSON object and no surrounding text. A compatibility wrapper is accepted when the endpoint requires it:",
            "<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
            '{"candidates":[...]}',
            "</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
            "Do not return code, URLs, source titles, DOI values, document IDs, explanations, reasoning, or claims not visible in the supplied text.",
            "Return at most two scalar candidates per requested parameter. If no eligible value is visible, return {\"candidates\":[]}.",
            "Each candidate must contain parameter_id, mathir_symbol, raw_value, normalized_value, normalized_unit, source_kind,",
            "evidence_locator, conditions, uncertainty, and transformation. evidence_locator must contain document_type and quoted_text;",
            "source_kind must be exactly one of PRIMARY_MEASUREMENT, REFERENCE_DATABASE, REVIEW_REPORTED, or USER_PROVIDED.",
            "normalized_value must be one finite JSON number, never a string, range, list, object, or null. If the text only gives a",
            "range, emit separate candidates only for scalar endpoints that are explicitly present in the exact quote; otherwise skip it.",
            "the quote must be exact text from the source. Use only a requested parameter and its requested output unit. Do not make a",
            "selection among candidates and do not turn a model assumption into literature evidence.",
            "Requested parameter subset:",
            json.dumps(prompt_requests, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "Controlled source-document metadata (not available for invention):",
            _bounded_json(source_document),
            "Local document text:",
            document_text,
        )
    )


def _parse_response(value: object, *, allow_plain_json: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise ParameterEvidenceExtractionError("parameter evidence extraction response must be text")
    match = _EVIDENCE_RESPONSE.fullmatch(value)
    if match is None and allow_plain_json:
        json_text = value.strip()
    elif match is None:
        raise ParameterEvidenceExtractionError("parameter evidence response must contain exactly one JSON block")
    else:
        json_text = match.group("json")
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as error:
        raise ParameterEvidenceExtractionError("parameter evidence JSON is invalid") from error
    candidates = _mapping(payload).get("candidates")
    if not isinstance(candidates, list):
        raise ParameterEvidenceExtractionError("parameter evidence JSON candidates must be a list")
    if len(candidates) > 8:
        raise ParameterEvidenceExtractionError("parameter evidence JSON returned more than eight candidates")
    counts: dict[str, int] = {}
    for candidate in candidates:
        parameter_id = _text(_mapping(candidate).get("parameter_id"))
        counts[parameter_id] = counts.get(parameter_id, 0) + 1
        if counts[parameter_id] > 2:
            raise ParameterEvidenceExtractionError(
                f"parameter evidence JSON returned more than two candidates for parameter {parameter_id}"
            )
    return [_mapping(candidate) for candidate in candidates]


def extract_parameter_evidence_candidates(
    *,
    blueprint: Mapping[str, object],
    source_document: Mapping[str, object],
    llm_call: Callable[[str], object],
    next_candidate_numbers: Mapping[str, int] | None = None,
    maximum_characters: int = 40_000,
    cache_directory: str | Path | None = None,
    max_snippets_per_parameter: int = 3,
    context_pages_before: int = 1,
    context_pages_after: int = 1,
    max_snippet_characters: int = 6_000,
    section_cache_directory: str | Path | None = None,
    llm_response_cache_directory: str | Path | None = None,
    minimum_keyword_hits: int = 2,
) -> dict[str, Any]:
    """Extract candidates from one immutable local document and validate quotes.

    Source bibliographic fields are copied from the controlled document record,
    rather than accepted from the LLM response.  This prevents an LLM from
    attributing a value to a different paper.
    """

    normalized_blueprint = normalize_model_blueprint(blueprint)
    document = _mapping(source_document)
    document_id = _text(document.get("document_id"))
    source_path = Path(_text(document.get("path"))).expanduser().resolve()
    if not document_id or not source_path.is_file():
        raise ParameterEvidenceExtractionError("source_document needs an existing document_id and local path")
    evidence_status = _text(document.get("evidence_status"))
    if evidence_status not in {"EXTRACTED_FULLTEXT", "USER_PROVIDED"}:
        raise ParameterEvidenceExtractionError("source_document evidence_status is unsupported")
    title = _text(document.get("title"))
    if not title:
        raise ParameterEvidenceExtractionError("source_document title is required")
    pages, page_count = _read_document_pages(
        source_path,
        cache_directory=Path(cache_directory).expanduser().resolve() if cache_directory else None,
    )
    section_cache_path: Path | None = None
    if section_cache_directory:
        section_key = hashlib.sha256(
            json.dumps(
                {
                    "pages_sha256": hashlib.sha256("\0".join(pages).encode("utf-8")).hexdigest(),
                    "blueprint_identity": model_blueprint_identity(normalized_blueprint),
                    "document_id": document_id,
                    "parameter_request_ids": sorted(
                        _text(value)
                        for value in document.get("parameter_request_ids") or []
                        if _text(value)
                    ),
                    "max_snippets_per_parameter": max_snippets_per_parameter,
                    "context_pages_before": context_pages_before,
                    "context_pages_after": context_pages_after,
                    "maximum_characters": maximum_characters,
                    "max_snippet_characters": max_snippet_characters,
                    "minimum_keyword_hits": minimum_keyword_hits,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        section_cache_path = Path(section_cache_directory).expanduser().resolve() / f"{section_key}.json"
    cached_section = _read_cache_json(section_cache_path)
    if (
        cached_section is not None
        and isinstance(cached_section.get("text"), str)
        and isinstance(cached_section.get("selection"), Mapping)
    ):
        document_text = str(cached_section["text"])
        selection = dict(cached_section["selection"])
    else:
        document_text, selection = _select_relevant_sections(
            blueprint=normalized_blueprint,
            source_document=document,
            pages=pages,
            max_snippets_per_parameter=max_snippets_per_parameter,
            context_pages_before=context_pages_before,
            context_pages_after=context_pages_after,
            max_snippet_characters=min(max(1, int(maximum_characters)), max(1, int(max_snippet_characters))),
            minimum_keyword_hits=minimum_keyword_hits,
        )
        _write_cache_json(section_cache_path, {"text": document_text, "selection": selection})
    if not document_text:
        return {
            "schema_version": PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
            "blueprint_identity": model_blueprint_identity(normalized_blueprint),
            "lineage": normalized_blueprint["lineage"],
            "source_document": {
                key: value for key, value in document.items() if key not in {"path", "sha256", "source_url"}
            },
            "extraction": {"mode": "TARGETED_SECTIONS", **selection},
            "candidates": [],
        }
    if not _normalized_text(document_text):
        raise ParameterEvidenceExtractionError("source document contains no extractable text")
    if llm_call is None:
        raise ParameterEvidenceExtractionError("a parameter evidence LLM callback is required")
    prompt_document = {key: value for key, value in document.items() if key not in {"path", "sha256", "source_url"}}
    prompt = build_parameter_evidence_extraction_prompt(
        blueprint=normalized_blueprint,
        source_document=prompt_document,
        document_text=document_text,
    )
    response_cache_path: Path | None = None
    if llm_response_cache_directory:
        cache_identity = str(getattr(llm_call, "cache_identity", "default"))
        cache_key = hashlib.sha256(
            (PARAMETER_EVIDENCE_PROMPT_VERSION + "\0" + cache_identity + "\0" + prompt).encode("utf-8")
        ).hexdigest()
        response_cache_path = (
            Path(llm_response_cache_directory).expanduser().resolve()
            / f"{cache_key}.json"
        )
    cached_response = _read_cache_json(response_cache_path)
    allow_plain_json = bool(cached_response and cached_response.get("plain_json", False))
    used_cached_response = bool(cached_response is not None and isinstance(cached_response.get("response"), str))

    def request_response() -> object:
        raw = _call_extraction_llm(
            llm_call,
            prompt,
            parameter_count=len(selection.get("matched_parameter_ids") or []),
        )
        return raw

    try:
        if used_cached_response:
            raw_response: object = cached_response["response"]
        else:
            raw_response = request_response()
            allow_plain_json = bool(getattr(llm_call, "supports_plain_json_response", False))
        try:
            raw_candidates = _parse_response(raw_response, allow_plain_json=allow_plain_json)
        except ParameterEvidenceExtractionError:
            if not used_cached_response:
                raise
            raw_response = request_response()
            allow_plain_json = bool(getattr(llm_call, "supports_plain_json_response", False))
            raw_candidates = _parse_response(raw_response, allow_plain_json=allow_plain_json)
            cached_response = None
    except ParameterEvidenceExtractionError:
        raise
    except Exception as error:
        raise ParameterEvidenceExtractionError(
            f"parameter evidence LLM call failed: {type(error).__name__}: {error}"
        ) from error
    requests = {request["parameter_id"]: request for request in normalized_blueprint["parameter_requests"]}
    counters = {str(key): int(value) for key, value in dict(next_candidate_numbers or {}).items()}
    candidates: list[dict[str, Any]] = []
    normalized_document_text = _normalized_text(document_text)
    for raw_candidate in raw_candidates:
        parameter_id = _text(raw_candidate.get("parameter_id"))
        request = requests.get(parameter_id)
        if request is None:
            raise ParameterEvidenceExtractionError("extracted candidate references a parameter not requested by the blueprint")
        if _text(raw_candidate.get("mathir_symbol")) != request["mathir_symbol"]:
            raise ParameterEvidenceExtractionError("extracted candidate MathIR symbol differs from the requested parameter")
        if _text(raw_candidate.get("normalized_unit")) != request["unit"]:
            raise ParameterEvidenceExtractionError("extracted candidate normalized unit differs from the requested unit")
        locator = _mapping(raw_candidate.get("evidence_locator"))
        quote = _normalized_text(locator.get("quoted_text"))
        if not quote or quote not in normalized_document_text:
            raise ParameterEvidenceExtractionError("extracted candidate quote is not present in the controlled source document")
        if page_count is not None and locator.get("page") is not None:
            try:
                page = int(locator["page"])
            except (TypeError, ValueError) as error:
                raise ParameterEvidenceExtractionError("extracted candidate page must be an integer") from error
            if page < 1 or page > page_count:
                raise ParameterEvidenceExtractionError("extracted candidate page lies outside the source document")
        number = counters.get(parameter_id, 0) + 1
        counters[parameter_id] = number
        controlled_source = {
            "doi": _text(document.get("doi")),
            "document_id": document_id,
            "title": title,
            "year": document.get("year"),
            "discovery_sources": list(document.get("discovery_sources") or []),
            "cross_validated": bool(document.get("cross_validated", False)),
        }
        candidate = {
            **raw_candidate,
            "candidate_id": f"PEC-{normalized_blueprint['lineage']['quantitative_idea_id']}-{parameter_id}-{number:03d}",
            "parameter_id": parameter_id,
            "mathir_symbol": request["mathir_symbol"],
            "evidence_status": evidence_status,
            "source": controlled_source,
        }
        try:
            candidates.append(normalize_parameter_evidence_candidate(candidate))
        except ParameterContractError as error:
            raise ParameterEvidenceExtractionError(f"extracted parameter candidate is invalid: {error}") from error
    if cached_response is None and isinstance(raw_response, str):
        _write_cache_json(
            response_cache_path,
            {"response": raw_response, "plain_json": allow_plain_json},
        )
    return {
        "schema_version": PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(normalized_blueprint),
        "lineage": normalized_blueprint["lineage"],
        "source_document": {
            key: value for key, value in document.items() if key not in {"path", "sha256", "source_url"}
        },
        "extraction": {"mode": "TARGETED_SECTIONS", **selection},
        "candidates": candidates,
    }


__all__ = [
    "PARAMETER_EVIDENCE_RESPONSE_SCHEMA",
    "PARAMETER_EVIDENCE_PROMPT_VERSION",
    "ParameterEvidenceExtractionError",
    "build_parameter_evidence_extraction_prompt",
    "extract_parameter_evidence_candidates",
]
