"""Strict extraction of parameter candidates from controlled local documents."""

from __future__ import annotations

import json
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


class ParameterEvidenceExtractionError(RuntimeError):
    """Raised when an extraction cannot be anchored to a local source document."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_text(value: object) -> str:
    return " ".join(_text(value).split())


def _bounded_json(value: Mapping[str, object], *, maximum: int = 12_000) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)[:maximum]


def _read_document_text(path: Path, *, maximum_characters: int) -> tuple[str, int | None]:
    suffix = path.suffix.casefold()
    try:
        if suffix in {".txt", ".md", ".csv"}:
            text = path.read_text(encoding="utf-8")
            return text[:maximum_characters], None
        if suffix != ".pdf":
            raise ParameterEvidenceExtractionError("parameter evidence documents must be PDF, TXT, MD, or CSV")
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            if sum(len(part) for part in parts) >= maximum_characters:
                break
        return "\n".join(parts)[:maximum_characters], len(reader.pages)
    except ParameterEvidenceExtractionError:
        raise
    except Exception as error:
        raise ParameterEvidenceExtractionError(
            f"cannot extract local parameter evidence text: {type(error).__name__}"
        ) from error


def build_parameter_evidence_extraction_prompt(
    *,
    blueprint: Mapping[str, object],
    source_document: Mapping[str, object],
    document_text: str,
) -> str:
    """Ask the LLM to locate values, never to fabricate a source or choice."""

    return "\n".join(
        (
            "Extract proposed scalar parameter evidence only from the supplied local document text.",
            "Return exactly one block and no surrounding text:",
            "<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
            '{"candidates":[...]}',
            "</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
            "Do not return code, URLs, source titles, DOI values, document IDs, or claims not visible in the supplied text.",
            "Each candidate must contain parameter_id, mathir_symbol, raw_value, normalized_value, normalized_unit, source_kind,",
            "evidence_locator, conditions, uncertainty, and transformation. evidence_locator must contain document_type and quoted_text;",
            "source_kind must be exactly one of PRIMARY_MEASUREMENT, REFERENCE_DATABASE, REVIEW_REPORTED, or USER_PROVIDED.",
            "normalized_value must be one finite JSON number, never a string, range, list, object, or null. If the text only gives a",
            "range, emit separate candidates only for scalar endpoints that are explicitly present in the exact quote; otherwise skip it.",
            "the quote must be exact text from the source. Use only a requested parameter and its requested output unit. Do not make a",
            "selection among candidates and do not turn a model assumption into literature evidence.",
            "Validated model blueprint:",
            _bounded_json(blueprint),
            "Controlled source-document metadata (not available for invention):",
            _bounded_json(source_document),
            "Local document text:",
            document_text,
        )
    )


def _parse_response(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise ParameterEvidenceExtractionError("parameter evidence extraction response must be text")
    match = _EVIDENCE_RESPONSE.fullmatch(value)
    if match is None:
        raise ParameterEvidenceExtractionError("parameter evidence response must contain exactly one JSON block")
    try:
        payload = json.loads(match.group("json"))
    except json.JSONDecodeError as error:
        raise ParameterEvidenceExtractionError("parameter evidence JSON is invalid") from error
    candidates = _mapping(payload).get("candidates")
    if not isinstance(candidates, list):
        raise ParameterEvidenceExtractionError("parameter evidence JSON candidates must be a list")
    return [_mapping(candidate) for candidate in candidates]


def extract_parameter_evidence_candidates(
    *,
    blueprint: Mapping[str, object],
    source_document: Mapping[str, object],
    llm_call: Callable[[str], object],
    next_candidate_numbers: Mapping[str, int] | None = None,
    maximum_characters: int = 40_000,
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
    document_text, page_count = _read_document_text(source_path, maximum_characters=maximum_characters)
    if not _normalized_text(document_text):
        raise ParameterEvidenceExtractionError("source document contains no extractable text")
    if llm_call is None:
        raise ParameterEvidenceExtractionError("a parameter evidence LLM callback is required")
    prompt_document = {key: value for key, value in document.items() if key not in {"path", "sha256", "source_url"}}
    try:
        raw_candidates = _parse_response(
            llm_call(
                build_parameter_evidence_extraction_prompt(
                    blueprint=normalized_blueprint,
                    source_document=prompt_document,
                    document_text=document_text,
                )
            )
        )
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
    return {
        "schema_version": PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(normalized_blueprint),
        "lineage": normalized_blueprint["lineage"],
        "source_document": {
            key: value for key, value in document.items() if key not in {"path", "sha256", "source_url"}
        },
        "candidates": candidates,
    }


__all__ = [
    "ParameterEvidenceExtractionError",
    "build_parameter_evidence_extraction_prompt",
    "extract_parameter_evidence_candidates",
]
