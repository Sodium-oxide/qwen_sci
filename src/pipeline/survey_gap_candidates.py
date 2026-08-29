"""LLM-assisted candidate gap extraction for Survey artifacts.

This module is deliberately downstream of the deterministic gap ledger.  The
LLM may propose a scientifically useful gap, but every proposal is normalized
to a versioned schema and must retain a section-aware source pointer.  No
candidate is treated as an adjudicated gap until Batch D processes it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .survey_idea_handoff import SourcePointer, canonical_fingerprint, stable_identifier


SURVEY_GAP_CANDIDATE_SCHEMA_VERSION = "survey_gap_candidate_v1"
SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION = "survey_gap_candidates_v1"
_MAX_SURVEY_CHARS = 32000
_MAX_PAPER_CHARS = 30000
_MAX_SECTION_CHARS = 9000


def _text(value: Any, *, limit: int = 12000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _parse_json(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, Mapping):
        return dict(value)
    raw = str(value or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return list(parsed) if isinstance(parsed, list) else {}


def _load_mapping(source: Mapping[str, Any] | str | Path | None, label: str) -> dict[str, Any]:
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return dict(value)


@dataclass(frozen=True)
class SectionAwarePaperInput:
    paper_id: str
    title: str = ""
    abstract: str = ""
    sections: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "sections": [
                {
                    "section_id": _text(section.get("section_id") or f"section_{index}"),
                    "heading": _text(section.get("heading") or section.get("title")),
                    "text": _text(section.get("text") or section.get("content"), limit=_MAX_SECTION_CHARS),
                }
                for index, section in enumerate(self.sections)
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GapCandidate:
    candidate_id: str
    subhypothesis_id: str
    gap_kind: str
    target_slot: str
    statement: str
    rationale: str = ""
    confidence: float = 0.0
    status: str = "candidate"
    support_level: str = "speculative"
    evidence_role: str = ""
    paper_ids: list[str] = field(default_factory=list)
    candidate_defect_tags: list[str] = field(default_factory=list)
    candidate_contribution_modes: list[str] = field(default_factory=list)
    source_pointers: list[SourcePointer] = field(default_factory=list)
    claim_scope: str = ""
    evidence_summary: str = ""
    extraction_method: str = ""

    @classmethod
    def create(
        cls,
        *,
        subhypothesis_id: str,
        gap_kind: str,
        target_slot: str,
        statement: str,
        **kwargs: Any,
    ) -> "GapCandidate":
        candidate_id = stable_identifier(
            "gap_candidate",
            subhypothesis_id,
            gap_kind,
            target_slot,
            _text(statement).casefold(),
        )
        return cls(
            candidate_id=candidate_id,
            subhypothesis_id=_text(subhypothesis_id),
            gap_kind=_text(gap_kind),
            target_slot=_text(target_slot),
            statement=_text(statement),
            **kwargs,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "subhypothesis_id": self.subhypothesis_id,
            "gap_kind": self.gap_kind,
            "target_slot": self.target_slot,
            "statement": self.statement,
            "rationale": self.rationale,
            "confidence": float(self.confidence),
            "status": self.status,
            "support_level": self.support_level,
            "evidence_role": self.evidence_role,
            "paper_ids": _texts(self.paper_ids),
            "candidate_defect_tags": _texts(self.candidate_defect_tags),
            "candidate_contribution_modes": _texts(self.candidate_contribution_modes),
            "source_pointers": [pointer.to_payload() for pointer in self.source_pointers],
            "claim_scope": self.claim_scope,
            "evidence_summary": self.evidence_summary,
            "extraction_method": self.extraction_method,
        }


_SOURCE_POINTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["artifact", "json_pointer"],
    "properties": {
        "artifact": {"type": "string", "minLength": 1},
        "json_pointer": {"type": "string", "minLength": 1},
        "paper_id": {"type": "string"},
        "section": {"type": "string"},
        "page": {"type": ["integer", "null"]},
        "paragraph_index": {"type": ["integer", "null"]},
    },
}

SURVEY_GAP_CANDIDATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Gap Candidate v1",
    "type": "object",
    "required": [
        "schema_version",
        "candidate_id",
        "subhypothesis_id",
        "gap_kind",
        "target_slot",
        "statement",
        "confidence",
        "status",
        "support_level",
        "paper_ids",
        "candidate_defect_tags",
        "candidate_contribution_modes",
        "source_pointers",
    ],
    "properties": {
        "schema_version": {"const": SURVEY_GAP_CANDIDATE_SCHEMA_VERSION},
        "candidate_id": {"type": "string", "minLength": 1},
        "subhypothesis_id": {"type": "string", "minLength": 1},
        "gap_kind": {"type": "string", "minLength": 1},
        "target_slot": {"type": "string", "minLength": 1},
        "statement": {"type": "string", "minLength": 1},
        "rationale": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "enum": ["candidate", "accepted", "downgraded", "rejected", "pending_verification"]},
        "support_level": {"type": "string", "enum": ["authoritative", "explicit", "cross_source", "speculative"]},
        "evidence_role": {"type": "string"},
        "paper_ids": {"type": "array", "items": {"type": "string"}},
        "candidate_defect_tags": {"type": "array", "items": {"type": "string"}},
        "candidate_contribution_modes": {"type": "array", "items": {"type": "string"}},
        "source_pointers": {"type": "array", "minItems": 1, "items": _SOURCE_POINTER_SCHEMA},
        "claim_scope": {"type": "string"},
        "evidence_summary": {"type": "string"},
        "extraction_method": {"type": "string"},
    },
}


def validate_gap_candidate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    if payload.get("schema_version") != SURVEY_GAP_CANDIDATE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SURVEY_GAP_CANDIDATE_SCHEMA_VERSION}")
    for key in ("candidate_id", "subhypothesis_id", "gap_kind", "target_slot", "statement"):
        if not _text(payload.get(key)):
            errors.append(f"payload.{key} must be a non-empty string")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        errors.append("payload.confidence must be between 0 and 1")
    if _text(payload.get("status")) not in {"candidate", "accepted", "downgraded", "rejected", "pending_verification"}:
        errors.append("payload.status is unsupported")
    if _text(payload.get("support_level")) not in {"authoritative", "explicit", "cross_source", "speculative"}:
        errors.append("payload.support_level is unsupported")
    for key in ("paper_ids", "candidate_defect_tags", "candidate_contribution_modes", "source_pointers"):
        if not isinstance(payload.get(key), list):
            errors.append(f"payload.{key} must be a list")
    pointers = payload.get("source_pointers")
    if isinstance(pointers, list) and not pointers:
        errors.append("payload.source_pointers must contain at least one grounded pointer")
    if isinstance(pointers, list):
        for index, pointer in enumerate(pointers):
            if not isinstance(pointer, Mapping):
                errors.append(f"payload.source_pointers[{index}] must be an object")
            elif not _text(pointer.get("artifact")) or not _text(pointer.get("json_pointer")):
                errors.append(f"payload.source_pointers[{index}] requires artifact and json_pointer")
    candidate_fingerprint = _text(payload.get("candidate_fingerprint"))
    if candidate_fingerprint and candidate_fingerprint != canonical_fingerprint(
        payload, exclude_fields={"candidate_fingerprint"}
    ):
        errors.append("candidate_fingerprint does not match canonical payload")
    return errors


def build_gap_candidate_payload(candidate: GapCandidate) -> dict[str, Any]:
    payload = {"schema_version": SURVEY_GAP_CANDIDATE_SCHEMA_VERSION, **candidate.to_payload()}
    payload["candidate_fingerprint"] = canonical_fingerprint(payload)
    return payload


SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Gap Candidate Ledger v1",
    "type": "object",
    "required": ["schema_version", "candidate_ledger_id", "candidates", "source_artifacts"],
    "properties": {
        "schema_version": {"const": SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION},
        "candidate_ledger_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string"},
        "survey_run_id": {"type": "string"},
        "project_context_fingerprint": {"type": "string"},
        "candidates": {"type": "array", "items": SURVEY_GAP_CANDIDATE_SCHEMA},
        "source_artifacts": {"type": "object"},
        "created_at": {"type": "string"},
        "ledger_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


def build_gap_candidate_ledger_payload(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
    *,
    project_id: str = "",
    survey_run_id: str = "",
    project_context_fingerprint: str = "",
    source_artifacts: Mapping[str, Any] | None = None,
    created_at: str = "",
) -> dict[str, Any]:
    candidate_payloads = [
        ({"schema_version": SURVEY_GAP_CANDIDATE_SCHEMA_VERSION, **candidate.to_payload()}
         if isinstance(candidate, GapCandidate)
         else _candidate_payload_for_ledger(candidate))
        for candidate in candidates
    ]
    ledger_id = stable_identifier("candidate_ledger", project_id, survey_run_id)
    payload = {
        "schema_version": SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION,
        "candidate_ledger_id": ledger_id,
        "project_id": _text(project_id),
        "survey_run_id": _text(survey_run_id),
        "project_context_fingerprint": _text(project_context_fingerprint),
        "candidates": candidate_payloads,
        "source_artifacts": dict(source_artifacts or {}),
        "created_at": _text(created_at),
    }
    payload["ledger_fingerprint"] = canonical_fingerprint(payload)
    return payload


def _candidate_payload_for_ledger(candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(candidate)
    payload.setdefault("schema_version", SURVEY_GAP_CANDIDATE_SCHEMA_VERSION)
    return payload


def validate_gap_candidate_ledger_payload(payload: Any, *, verify_fingerprint: bool = False) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION}")
    for key in ("candidate_ledger_id", "source_artifacts"):
        if key == "source_artifacts":
            if not isinstance(payload.get(key), Mapping):
                errors.append("payload.source_artifacts must be an object")
        elif not _text(payload.get(key)):
            errors.append(f"payload.{key} must be a non-empty string")
    if not isinstance(payload.get("candidates"), list):
        errors.append("payload.candidates must be a list")
    else:
        for index, candidate in enumerate(payload["candidates"]):
            errors.extend(f"payload.candidates[{index}].{error}" for error in validate_gap_candidate_payload(candidate))
    if verify_fingerprint and _text(payload.get("ledger_fingerprint")) != canonical_fingerprint(payload, exclude_fields={"ledger_fingerprint"}):
        errors.append("ledger_fingerprint does not match canonical payload")
    return errors


def _section_list(paper: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_sections = paper.get("sections") or paper.get("fulltext_sections")
    if isinstance(raw_sections, Mapping):
        raw_sections = [
            {"section_id": key, "heading": key, "text": value}
            for key, value in raw_sections.items()
        ]
    sections = []
    for index, raw in enumerate(_records(raw_sections)):
        heading = _text(raw.get("heading") or raw.get("title") or raw.get("name") or f"Section {index + 1}")
        text = _text(raw.get("text") or raw.get("content") or raw.get("body"), limit=_MAX_SECTION_CHARS)
        if text:
            sections.append({"section_id": _text(raw.get("section_id") or f"section_{index}"), "heading": heading, "text": text})
    if sections:
        return sections
    fulltext = _text(paper.get("fulltext") or paper.get("text") or paper.get("body"), limit=_MAX_PAPER_CHARS)
    if not fulltext:
        return []
    matches = list(re.finditer(r"(?im)^\s{0,3}#{1,6}\s+(.+?)\s*$", fulltext))
    if not matches:
        return [{"section_id": "fulltext", "heading": "Full text", "text": fulltext[:_MAX_SECTION_CHARS]}]
    result: list[dict[str, str]] = []
    if matches[0].start() > 0:
        result.append({"section_id": "preamble", "heading": "Preamble", "text": fulltext[: matches[0].start()].strip()[:_MAX_SECTION_CHARS]})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(fulltext)
        text = fulltext[match.end() : end].strip()[:_MAX_SECTION_CHARS]
        if text:
            result.append({"section_id": f"section_{index}", "heading": _text(match.group(1)), "text": text})
    return result


def build_section_aware_paper_input(
    paper: SectionAwarePaperInput | Mapping[str, Any],
    *,
    max_chars: int = _MAX_PAPER_CHARS,
) -> SectionAwarePaperInput:
    """Normalize a paper while retaining section boundaries for provenance."""

    if isinstance(paper, SectionAwarePaperInput):
        return paper
    source = _mapping(paper)
    paper_id = _text(source.get("paper_id") or source.get("paperId") or source.get("openalex_id") or source.get("doi") or "unknown-paper")
    title = _text(source.get("title") or source.get("paper_title"))
    abstract = _text(source.get("abstract"), limit=_MAX_SECTION_CHARS)
    sections = _section_list(source)
    metadata = {
        key: source[key]
        for key in ("doi", "year", "venue", "provider", "publication_type")
        if source.get(key) not in (None, "")
    }
    normalized = SectionAwarePaperInput(paper_id, title, abstract, sections, metadata)
    budget = max(1000, int(max_chars))
    serialized = json.dumps(normalized.to_payload(), ensure_ascii=False)
    if len(serialized) <= budget:
        return normalized
    remaining = max(1000, budget - len(title) - len(abstract) - 300)
    clipped_sections: list[dict[str, str]] = []
    for section in sections:
        if remaining <= 0:
            break
        text = section["text"][:remaining]
        clipped_sections.append({**section, "text": text})
        remaining -= len(text)
    return SectionAwarePaperInput(paper_id, title, abstract, clipped_sections, metadata)


def _survey_text(survey_markdown: str | Path | None, survey_json: Mapping[str, Any] | str | Path | None) -> str:
    if survey_markdown is not None:
        path = Path(survey_markdown) if not isinstance(survey_markdown, str) else Path(survey_markdown)
        try:
            return path.read_text(encoding="utf-8").strip()[:_MAX_SURVEY_CHARS]
        except OSError:
            return str(survey_markdown).strip()[:_MAX_SURVEY_CHARS]
    survey = _load_mapping(survey_json, "survey JSON")
    for key in ("survey", "final_survey", "markdown", "content", "text"):
        if _text(survey.get(key)):
            return str(survey[key]).strip()[:_MAX_SURVEY_CHARS]
    return json.dumps(survey, ensure_ascii=False)[:_MAX_SURVEY_CHARS]


def _compact_ledger(ledger: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
    payload = _load_mapping(ledger, "gap ledger")
    return {
        "project_id": payload.get("project_id", ""),
        "survey_run_id": payload.get("survey_run_id", ""),
        "profile_resolution": payload.get("profile_resolution", {}),
        "gaps": [
            {
                key: gap.get(key, "")
                for key in ("gap_id", "subhypothesis_id", "gap_kind", "target_slot", "statement", "priority")
            }
            for gap in _records(payload.get("gaps"))
        ],
    }


def build_survey_gap_extraction_prompt(
    survey_text: str,
    *,
    deterministic_ledger: Mapping[str, Any] | None = None,
    profile_resolution: Mapping[str, Any] | None = None,
) -> str:
    schema = {
        "candidates": [
            {
                "subhypothesis_id": "existing SH id when grounded, otherwise GLOBAL",
                "gap_kind": "domain-neutral gap category",
                "target_slot": "specific scientific slot",
                "statement": "one falsifiable unresolved constraint",
                "rationale": "why the survey text supports this candidate",
                "confidence": 0.0,
                "source_pointers": [{"artifact": "survey.md", "json_pointer": "/sections/<section>", "section": "heading"}],
                "paper_ids": [],
                "evidence_role": "required evidence role if stated",
                "claim_scope": "scope or limitation",
            }
        ]
    }
    return """You extract candidate scientific research gaps from a Survey draft. Return exactly one JSON object and no Markdown.
Do not invent a result, cite a paper that is not present, or convert a gap into a software/ML task. A candidate is a bounded unresolved relation, assumption, validity condition, measurement issue, comparator, mechanism, or counterexample opportunity.
Every candidate must include a source pointer into the supplied Survey text. Keep sub-hypothesis IDs when present; use GLOBAL only when no mapping is possible. Unknown categories must remain domain-neutral rather than being forced into Computer Science.

Output shape:
""" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n\nStructured deterministic ledger:\n" + json.dumps(deterministic_ledger or {}, ensure_ascii=False, indent=2) + "\n\nProfile resolution:\n" + json.dumps(profile_resolution or {}, ensure_ascii=False, indent=2) + "\n\nSurvey text:\n" + _text(survey_text, limit=_MAX_SURVEY_CHARS)


def build_paper_limitation_extraction_prompt(
    paper: SectionAwarePaperInput | Mapping[str, Any],
    *,
    gap_context: Mapping[str, Any] | None = None,
) -> str:
    normalized = paper if isinstance(paper, SectionAwarePaperInput) else build_section_aware_paper_input(paper)
    schema = {
        "candidates": [
            {
                "subhypothesis_id": "SH id when supplied by context, otherwise GLOBAL",
                "gap_kind": "limitation category",
                "target_slot": "scientific slot affected",
                "statement": "limitation or unresolved gap grounded in this paper",
                "rationale": "evidence from the paper",
                "confidence": 0.0,
                "section": "section heading",
                "source_pointers": [{"artifact": "paper", "json_pointer": "/sections/<section_id>", "paper_id": normalized.paper_id, "section": "heading"}],
            }
        ]
    }
    return """You identify research-gap candidates from one paper, using only the supplied title, abstract, and section text. Return one JSON object and no Markdown.
Report limitations, missing assumptions, boundary conditions, unresolved mechanisms, measurement limitations, comparator deficits, or explicit contradictions. Do not treat absence of an implementation, dataset, benchmark, or training signal as a scientific gap unless the paper explicitly makes it part of the claim. Every item needs a source pointer naming the paper section.

Output shape:
""" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n\nGap context:\n" + json.dumps(gap_context or {}, ensure_ascii=False, indent=2) + "\n\nSection-aware paper:\n" + json.dumps(normalized.to_payload(), ensure_ascii=False, indent=2)


def _pointer(value: Any, *, artifact: str, default_pointer: str, paper_id: str = "", section: str = "") -> SourcePointer:
    raw = _mapping(value)
    return SourcePointer(
        artifact=_text(raw.get("artifact") or artifact),
        json_pointer=_text(raw.get("json_pointer") or default_pointer) or "/",
        paper_id=_text(raw.get("paper_id") or paper_id),
        section=_text(raw.get("section") or section),
        page=raw.get("page") if isinstance(raw.get("page"), int) else None,
        paragraph_index=raw.get("paragraph_index") if isinstance(raw.get("paragraph_index"), int) else None,
    )


def _candidate_with_pointers(
    candidate: GapCandidate,
    pointers: list[SourcePointer],
) -> GapCandidate:
    return GapCandidate(**{**candidate.__dict__, "source_pointers": pointers})


def _section_index_from_pointer(pointer: SourcePointer) -> int | None:
    match = re.fullmatch(r"/sections/(\d+)", _text(pointer.json_pointer))
    return int(match.group(1)) if match else None


def _survey_sections(survey_text: str) -> list[str]:
    return [
        _text(match.group(1))
        for match in re.finditer(r"(?im)^\s{0,3}#{1,6}\s+(.+?)\s*$", survey_text)
        if _text(match.group(1))
    ]


def _verify_survey_candidate(
    candidate: GapCandidate,
    survey_text: str,
) -> GapCandidate | None:
    sections = _survey_sections(survey_text)
    if not sections:
        return None
    verified: list[SourcePointer] = []
    for pointer in candidate.source_pointers:
        if _text(pointer.artifact) != "survey.md":
            continue
        section_index = next(
            (
                index
                for index, heading in enumerate(sections)
                if _text(pointer.section).casefold() == heading.casefold()
            ),
            None,
        )
        if section_index is None:
            section_index = _section_index_from_pointer(pointer)
        if section_index is None or not 0 <= section_index < len(sections):
            continue
        verified.append(
            SourcePointer(
                artifact="survey.md",
                json_pointer=f"/sections/{section_index}",
                section=sections[section_index],
                page=pointer.page,
                paragraph_index=pointer.paragraph_index,
            )
        )
    return _candidate_with_pointers(candidate, verified) if verified else None


def _verify_paper_candidate(
    candidate: GapCandidate,
    paper: SectionAwarePaperInput,
) -> GapCandidate | None:
    sections = list(paper.sections)
    verified: list[SourcePointer] = []
    for pointer in candidate.source_pointers:
        if _text(pointer.artifact) != "paper":
            continue
        pointer_paper_id = _text(pointer.paper_id)
        if pointer_paper_id and pointer_paper_id != paper.paper_id:
            continue
        if _text(pointer.json_pointer) == "/abstract" and paper.abstract:
            verified.append(
                SourcePointer(
                    artifact="paper",
                    json_pointer="/abstract",
                    paper_id=paper.paper_id,
                    section="Abstract",
                    page=pointer.page,
                    paragraph_index=pointer.paragraph_index,
                )
            )
            continue
        section_index = next(
            (
                index
                for index, section in enumerate(sections)
                if _text(pointer.section).casefold()
                in {_text(section.get("heading")).casefold(), _text(section.get("section_id")).casefold()}
            ),
            None,
        )
        if section_index is None:
            section_index = _section_index_from_pointer(pointer)
        if section_index is None or not 0 <= section_index < len(sections):
            continue
        section = sections[section_index]
        verified.append(
            SourcePointer(
                artifact="paper",
                json_pointer=f"/sections/{section_index}",
                paper_id=paper.paper_id,
                section=_text(section.get("heading") or section.get("section_id")),
                page=pointer.page,
                paragraph_index=pointer.paragraph_index,
            )
        )
    return _candidate_with_pointers(candidate, verified) if verified else None


def _candidate_items(response: Any) -> list[dict[str, Any]]:
    payload = _parse_json(response)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    for key in ("candidates", "gap_candidates", "limitations", "gaps"):
        records = _records(payload.get(key))
        if records:
            return records
    return [payload] if _text(payload.get("statement")) else []


def _normalize_candidate(
    raw: Mapping[str, Any],
    *,
    method: str,
    default_subhypothesis_id: str = "GLOBAL",
    default_paper_id: str = "",
    default_artifact: str = "survey.md",
    default_pointer: str = "/",
    default_section: str = "",
    default_support_level: str = "speculative",
) -> GapCandidate | None:
    statement = _text(raw.get("statement") or raw.get("gap_statement") or raw.get("limitation"))
    if not statement:
        return None
    subhypothesis_id = _text(raw.get("subhypothesis_id") or raw.get("sub_hypothesis_id")) or default_subhypothesis_id
    gap_kind = _text(raw.get("gap_kind") or raw.get("category") or "unmapped_gap:llm_candidate")
    target_slot = _text(raw.get("target_slot") or raw.get("slot") or "scientific_constraint")
    try:
        confidence = float(raw.get("confidence", raw.get("score", 0.5)))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    source_values = raw.get("source_pointers") or raw.get("source_pointer") or []
    if isinstance(source_values, Mapping):
        source_values = [source_values]
    pointers = [
        _pointer(
            value,
            artifact=default_artifact,
            default_pointer=default_pointer,
            paper_id=default_paper_id,
            section=_text(raw.get("section") or default_section),
        )
        for value in source_values
        if isinstance(value, Mapping)
    ]
    if not pointers:
        return None
    support = _text(raw.get("support_level")) or default_support_level
    if support not in {"authoritative", "explicit", "cross_source", "speculative"}:
        support = default_support_level
    return GapCandidate.create(
        subhypothesis_id=subhypothesis_id,
        gap_kind=gap_kind,
        target_slot=target_slot,
        statement=statement,
        rationale=_text(raw.get("rationale") or raw.get("reason")),
        confidence=confidence,
        status="candidate",
        support_level=support,
        evidence_role=_text(raw.get("evidence_role") or raw.get("expected_evidence_role")),
        paper_ids=_texts(raw.get("paper_ids") or ([default_paper_id] if default_paper_id else [])),
        candidate_defect_tags=_texts(raw.get("candidate_defect_tags") or raw.get("defect_tags") or [gap_kind]),
        candidate_contribution_modes=_texts(raw.get("candidate_contribution_modes") or raw.get("contribution_modes")),
        source_pointers=pointers,
        claim_scope=_text(raw.get("claim_scope") or raw.get("scope")),
        evidence_summary=_text(raw.get("evidence_summary") or raw.get("evidence")),
        extraction_method=method,
    )


def extract_survey_gap_candidates(
    *,
    llm_call: Callable[[str], Any],
    survey_markdown: str | Path | None = None,
    survey_json: Mapping[str, Any] | str | Path | None = None,
    deterministic_ledger: Mapping[str, Any] | str | Path | None = None,
    profile_resolution: Mapping[str, Any] | None = None,
) -> list[GapCandidate]:
    survey_text = _survey_text(survey_markdown, survey_json)
    prompt = build_survey_gap_extraction_prompt(
        survey_text,
        deterministic_ledger=_compact_ledger(deterministic_ledger),
        profile_resolution=profile_resolution,
    )
    response = llm_call(prompt)
    result: list[GapCandidate] = []
    for index, raw in enumerate(_candidate_items(response)):
        candidate = _normalize_candidate(
            raw,
            method="survey_prose_llm",
            default_artifact="survey.md",
            default_pointer=f"/llm_candidates/{index}",
        )
        candidate = (
            _verify_survey_candidate(candidate, survey_text)
            if candidate is not None
            else None
        )
        if candidate is not None:
            result.append(candidate)
    return result


def extract_paper_limitation_candidates(
    *,
    papers: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    llm_call: Callable[[str], Any],
    gap_context: Mapping[str, Any] | None = None,
) -> list[GapCandidate]:
    if isinstance(papers, SectionAwarePaperInput):
        paper_items = [papers.to_payload()]
    elif isinstance(papers, Mapping):
        paper_items = [dict(papers)]
    else:
        paper_items = [dict(item) for item in papers if isinstance(item, Mapping)]
    result: list[GapCandidate] = []
    for paper_index, paper in enumerate(paper_items):
        normalized = build_section_aware_paper_input(paper)
        prompt = build_paper_limitation_extraction_prompt(normalized, gap_context=gap_context)
        response = llm_call(prompt)
        for candidate_index, raw in enumerate(_candidate_items(response)):
            raw = dict(raw)
            section = _text(raw.get("section"))
            section_index = next((index for index, item in enumerate(normalized.sections) if item["heading"].casefold() == section.casefold() or item["section_id"] == section), None)
            pointer = f"/sections/{section_index if section_index is not None else 0}"
            if not raw.get("source_pointers") and not raw.get("source_pointer") and section:
                raw["source_pointers"] = [{
                    "artifact": "paper",
                    "json_pointer": pointer,
                    "paper_id": normalized.paper_id,
                    "section": section,
                }]
            candidate = _normalize_candidate(
                raw,
                method="paper_limitation_llm",
                default_subhypothesis_id=_text((gap_context or {}).get("subhypothesis_id")) or "GLOBAL",
                default_paper_id=normalized.paper_id,
                default_artifact="paper",
                default_pointer=pointer,
                default_section=section or (normalized.sections[section_index]["heading"] if section_index is not None else ""),
                default_support_level="explicit",
            )
            candidate = (
                _verify_paper_candidate(candidate, normalized)
                if candidate is not None
                else None
            )
            if candidate is not None:
                result.append(candidate)
    return result


def extract_gap_candidates(
    *,
    llm_call: Callable[[str], Any],
    survey_markdown: str | Path | None = None,
    survey_json: Mapping[str, Any] | str | Path | None = None,
    deterministic_ledger: Mapping[str, Any] | str | Path | None = None,
    profile_resolution: Mapping[str, Any] | None = None,
    papers: Sequence[Mapping[str, Any]] | None = None,
    extract_paper_limitations: bool = True,
) -> list[GapCandidate]:
    """Run Survey-prose extraction and optional section-aware paper extraction."""

    candidates = extract_survey_gap_candidates(
        llm_call=llm_call,
        survey_markdown=survey_markdown,
        survey_json=survey_json,
        deterministic_ledger=deterministic_ledger,
        profile_resolution=profile_resolution,
    )
    if extract_paper_limitations and papers:
        candidates.extend(
            extract_paper_limitation_candidates(
                papers=papers,
                llm_call=llm_call,
                gap_context=profile_resolution,
            )
        )
    return candidates


extract_survey_prose_candidates = extract_survey_gap_candidates


__all__ = [
    "GapCandidate",
    "SectionAwarePaperInput",
    "SURVEY_GAP_CANDIDATE_SCHEMA",
    "SURVEY_GAP_CANDIDATE_SCHEMA_VERSION",
    "SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA_VERSION",
    "SURVEY_GAP_CANDIDATE_LEDGER_SCHEMA",
    "build_gap_candidate_payload",
    "build_gap_candidate_ledger_payload",
    "build_paper_limitation_extraction_prompt",
    "build_section_aware_paper_input",
    "build_survey_gap_extraction_prompt",
    "extract_gap_candidates",
    "extract_paper_limitation_candidates",
    "extract_survey_gap_candidates",
    "extract_survey_prose_candidates",
    "validate_gap_candidate_payload",
    "validate_gap_candidate_ledger_payload",
]
