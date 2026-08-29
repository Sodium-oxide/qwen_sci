"""English-only, evidence-traceable research report generation.

This module is deliberately a read-only presentation layer.  It never changes
the scientific workflow state, promotes a hypothesis to evidence, or invents a
combined gap.  It freezes a project snapshot into a report model, produces
deterministic tables and prose, optionally asks an LLM for tightly constrained
English narrative paragraphs, and renders an IEEEtran-compatible LaTeX bundle.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import os
import re
import shutil
import subprocess
import time


REPORT_SCHEMA_VERSION = "research_traceability_report_v2"
REPORT_LANGUAGE = "en"
MAX_NARRATIVE_RETRIES = 2
RESTRICTED_BRIDGE_DISCLAIMER = (
    "This hypothesis is supported only by component or bridge evidence and must not be presented "
    "as validation of the final research object."
)
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_UNSAFE_NARRATIVE_RE = re.compile(
    r"\b(?:prove(?:s|d)?|proven|validate(?:s|d)?|definitively validated|"
    r"conclusively established|demonstrates? final validation|guarantees?)\b",
    flags=re.IGNORECASE,
)
_CITATION_TOKEN_RE = re.compile(r"\[\[CITE:([A-Za-z0-9_:-]+)\]\]")
_LATEX_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
_UNRESOLVED_VALUE_RE = re.compile(
    r"\b(?:tbd|todo|unknown|unresolved|not[ _-]?recorded|pending|n/?a|none|"
    r"requires?[_ -](?:enrichment|verification|resolution)|to[_ -]?be[_ -]?(?:determined|optimized))\b",
    flags=re.IGNORECASE,
)
_RESULT_OVERCLAIM_RE = re.compile(
    r"\b(?:we|this (?:study|report|work)|the (?:experiment|analysis))\s+"
    r"(?:found|observed|measured|obtained|achieved|confirmed|established|showed)\b|"
    r"\b(?:the )?(?:results?|findings?)\s+(?:show|demonstrate|confirm|establish)\b",
    flags=re.IGNORECASE,
)
_SELF_CRITIQUE_MIN_LENGTH = 20


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None or value == "":
        return []
    return [value]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _first(*values: Any) -> str:
    for value in values:
        compact = _text(value)
        if compact:
            return compact
    return ""


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        compact = _text(value)
        if compact and compact not in seen:
            seen.add(compact)
            result.append(compact)
    return result


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_identifier(value: Any, fallback: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", _text(value)).strip("._-")
    return raw or fallback


def _english_or_placeholder(value: Any, *, field: str) -> tuple[str, bool]:
    """Return English-safe text without silently translating source content."""
    compact = _text(value)
    if not compact:
        return f"No {field} was recorded in the frozen project snapshot.", False
    if _CJK_RE.search(compact):
        return f"English rendering pending source-grounded translation of {field}.", True
    return compact, False


def _english_list(values: Any, *, field: str) -> tuple[list[str], bool]:
    rendered: list[str] = []
    needs_translation = False
    for value in _items(values):
        text, pending = _english_or_placeholder(value, field=field)
        if _text(value):
            rendered.append(text)
        needs_translation = needs_translation or pending
    return _unique(rendered), needs_translation


def _list_text(values: Any, fallback: str = "not recorded") -> str:
    compact = _unique(_items(values))
    return "; ".join(compact) if compact else fallback


def _reference_aliases(record: dict[str, Any]) -> list[str]:
    payload = _mapping(record.get("papergraph_input"))
    return _unique([
        record.get("paper_id"), record.get("id"), record.get("unique_key"),
        record.get("doi"), payload.get("doi"), record.get("citation"),
    ])


def _normalise_doi(value: Any) -> str:
    doi = _text(value).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.strip().rstrip(".,;)")


def _reference_identity(record: dict[str, Any], ordinal: int) -> str:
    """Create a stable bibliographic identity before a display key is assigned.

    DOI is authoritative.  For records without DOI, a normalized title plus
    year and first author distinguishes records without relying on ingestion
    order or a transient PaperGraph identifier.
    """
    payload = _mapping(record.get("papergraph_input"))
    doi = _normalise_doi(_first(record.get("doi"), payload.get("doi")))
    if doi:
        return f"doi:{doi}"
    title = _first(record.get("title"), payload.get("title"))
    title_signature = re.sub(r"[^a-z0-9]+", "", title.lower())
    year = re.sub(r"[^0-9]", "", _first(record.get("year"), payload.get("year")))
    authors = _author_names(record)
    first_author = re.sub(r"[^a-z0-9]+", "", (authors[0] if authors else "").lower())
    if title_signature:
        return f"title:{title_signature}|year:{year or 'unknown'}|author:{first_author or 'unknown'}"
    fallback = _first(record.get("paper_id"), record.get("id"), record.get("unique_key"), f"record_{ordinal}")
    return f"record:{_safe_identifier(fallback, f'record_{ordinal}').lower()}"


def _stable_reference_key(identity: str) -> str:
    """Return a readable citation key that remains stable if catalogue order changes."""
    token = identity.split(":", 1)[-1].split("|", 1)[0]
    stem = re.sub(r"[^A-Za-z0-9]+", "_", token).lower()[:42].strip("_") or "reference"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
    return f"ref_{stem}_{digest}"


def _record_subhypothesis_ids(record: dict[str, Any]) -> list[str]:
    payload = _mapping(record.get("papergraph_input"))
    values: list[Any] = []
    for source in (record, payload, _mapping(record.get("alignment"))):
        for key in ("sub_hypothesis_id", "subhypothesis_id", "sub_hypothesis_ids", "subhypothesis_ids"):
            values.extend(_items(source.get(key)))
    return _unique(values)


def _collect_source_unit_ids(value: Any) -> list[str]:
    """Collect explicit source-unit identifiers without treating free text as provenance."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in {"source_unit_id", "source_unit_ids", "sourceunitid", "sourceunitids"}:
                found.extend(_items(nested))
            elif isinstance(nested, (dict, list, tuple)):
                found.extend(_collect_source_unit_ids(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_collect_source_unit_ids(nested))
    return _unique(found)


def _merge_reference_field(current: Any, candidate: Any) -> Any:
    """Prefer the first concrete value, but replace a translation placeholder."""
    current_text = _text(current)
    candidate_text = _text(candidate)
    if not current_text or current_text.startswith("English rendering pending"):
        return candidate if candidate_text else current
    return current


def _author_names(record: dict[str, Any]) -> list[str]:
    payload = _mapping(record.get("papergraph_input"))
    raw = record.get("authors") or payload.get("authors") or []
    names: list[str] = []
    if isinstance(raw, str):
        names = [part.strip() for part in re.split(r"\s*;\s*|\s+and\s+", raw) if part.strip()]
    else:
        for item in _items(raw):
            if isinstance(item, dict):
                names.append(_first(item.get("name"), item.get("author"), item.get("display_name")))
            else:
                names.append(_text(item))
    return _unique(names)[:20]


def _reference_catalog(papergraph: Any) -> tuple[list[dict[str, Any]], dict[str, str], bool]:
    """Normalize and genuinely deduplicate bibliography records.

    Records with the same DOI, or the same title/year/first-author fallback,
    become one bibliography entry.  All original record identifiers and every
    explicit source unit remain attached to that entry for later audit.
    """
    references_by_identity: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    translation_pending = False
    for ordinal, raw in enumerate((item for item in _items(papergraph) if isinstance(item, dict)), start=1):
        record = _mapping(raw)
        payload = _mapping(record.get("papergraph_input"))
        identity = _reference_identity(record, ordinal)
        key = _stable_reference_key(identity)
        title, pending = _english_or_placeholder(
            _first(record.get("title"), payload.get("title"), record.get("paper_id"), identity), field="paper title"
        )
        translation_pending = translation_pending or pending
        venue, venue_pending = _english_or_placeholder(
            _first(record.get("venue"), record.get("journal"), payload.get("venue"), payload.get("journal")),
            field="publication venue",
        )
        translation_pending = translation_pending or venue_pending
        authors, author_pending = _english_list(_author_names(record), field="author name")
        translation_pending = translation_pending or author_pending
        method, method_pending = _english_or_placeholder(
            _first(record.get("method"), payload.get("method")), field="literature method"
        )
        scenario, scenario_pending = _english_or_placeholder(
            _first(record.get("scenario"), payload.get("scenario")), field="literature scenario"
        )
        benchmark, benchmark_pending = _english_or_placeholder(
            _first(record.get("benchmark"), payload.get("benchmark")), field="literature benchmark"
        )
        limitations: list[str] = []
        for raw_limitation in (
            _items(record.get("limitations"))
            + _items(record.get("reported_limitations"))
            + _items(record.get("methodological_limitations"))
        ):
            if not _text(raw_limitation):
                continue
            limitation, limitation_pending = _english_or_placeholder(raw_limitation, field="source-stated limitation")
            limitations.append(limitation)
            translation_pending = translation_pending or limitation_pending
        translation_pending = translation_pending or method_pending or scenario_pending or benchmark_pending
        paper_id = _first(record.get("paper_id"), record.get("id"), record.get("unique_key"), f"paper_{ordinal}")
        source_unit_ids = _collect_source_unit_ids(record)
        if identity not in references_by_identity:
            references_by_identity[identity] = {
                "reference_key": key,
                "canonical_identity": identity,
                "paper_id": paper_id,
                "source_paper_ids": [paper_id],
                "source_record_ids": _reference_aliases(record),
                "title": title,
                "authors": authors,
                "year": _first(record.get("year"), payload.get("year")),
                "venue": venue if _text(venue) and not venue.startswith("No publication") else "",
                "doi": _normalise_doi(_first(record.get("doi"), payload.get("doi"))),
                "url": _first(record.get("url"), record.get("pdf_url"), payload.get("url")),
                "method": method if _first(record.get("method"), payload.get("method")) else "",
                "scenario": scenario if _first(record.get("scenario"), payload.get("scenario")) else "",
                "benchmark": benchmark if _first(record.get("benchmark"), payload.get("benchmark")) else "",
                "limitations": _unique(limitations),
                "source_unit_ids": source_unit_ids,
                "sub_hypothesis_ids": _record_subhypothesis_ids(record),
                "deduplicated_record_count": 1,
            }
        else:
            reference = references_by_identity[identity]
            reference["source_paper_ids"] = _unique(_items(reference.get("source_paper_ids")) + [paper_id])
            reference["source_record_ids"] = _unique(_items(reference.get("source_record_ids")) + _reference_aliases(record))
            reference["source_unit_ids"] = _unique(_items(reference.get("source_unit_ids")) + source_unit_ids)
            reference["sub_hypothesis_ids"] = _unique(_items(reference.get("sub_hypothesis_ids")) + _record_subhypothesis_ids(record))
            reference["authors"] = _unique(_items(reference.get("authors")) + authors)
            reference["limitations"] = _unique(_items(reference.get("limitations")) + limitations)
            reference["deduplicated_record_count"] = int(reference.get("deduplicated_record_count") or 1) + 1
            for field, candidate in {
                "title": title,
                "year": _first(record.get("year"), payload.get("year")),
                "venue": venue if _text(venue) and not venue.startswith("No publication") else "",
                "doi": _normalise_doi(_first(record.get("doi"), payload.get("doi"))),
                "url": _first(record.get("url"), record.get("pdf_url"), payload.get("url")),
                "method": method if _first(record.get("method"), payload.get("method")) else "",
                "scenario": scenario if _first(record.get("scenario"), payload.get("scenario")) else "",
                "benchmark": benchmark if _first(record.get("benchmark"), payload.get("benchmark")) else "",
            }.items():
                reference[field] = _merge_reference_field(reference.get(field), candidate)
        for alias in _reference_aliases(record) + [paper_id, identity]:
            aliases[alias] = key
    references = sorted(references_by_identity.values(), key=lambda item: item["reference_key"])
    return references, aliases, translation_pending


def _extract_subhypothesis_ids(record: dict[str, Any], known_ids: set[str]) -> list[str]:
    nested = _mapping(record.get("alignment"))
    candidates: list[Any] = []
    for source in (record, nested, _mapping(record.get("papergraph_input"))):
        candidates.extend(_items(source.get("sub_hypothesis_id")))
        candidates.extend(_items(source.get("subhypothesis_id")))
        candidates.extend(_items(source.get("sub_hypothesis_ids")))
        candidates.extend(_items(source.get("subhypothesis_ids")))
    return [item for item in _unique(candidates) if item in known_ids]


def _normalize_subhypotheses(project: dict[str, Any], references: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    raw_subhypotheses = [item for item in _items(project.get("sub_hypotheses")) if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    pending = False
    for index, raw in enumerate(raw_subhypotheses, start=1):
        item = _mapping(raw)
        sub_id = _first(item.get("id"), item.get("sub_hypothesis_id"), item.get("sh_id"), f"SH{index}")
        title, flag = _english_or_placeholder(_first(item.get("title"), item.get("name"), sub_id), field=f"title for {sub_id}")
        pending = pending or flag
        scientific_object, flag = _english_or_placeholder(
            _first(item.get("scientific_object"), item.get("object"), item.get("target_object")),
            field=f"scientific object for {sub_id}",
        )
        pending = pending or flag
        inputs, flag = _english_list(
            item.get("independent_variables") or item.get("input_variables") or item.get("interventions"),
            field=f"input variable for {sub_id}",
        )
        outcomes, flag_outcomes = _english_list(
            item.get("dependent_variables") or item.get("outcomes") or item.get("measurement_variables"),
            field=f"outcome for {sub_id}",
        )
        pending = pending or flag or flag_outcomes
        comparison, flag = _english_or_placeholder(
            _first(item.get("comparison"), item.get("baseline"), item.get("comparator")),
            field=f"comparison for {sub_id}",
        )
        pending = pending or flag
        boundary, flag = _english_or_placeholder(
            _first(item.get("boundary_conditions"), item.get("quantifiable_bounds"), item.get("threshold_to_test")),
            field=f"boundary condition for {sub_id}",
        )
        pending = pending or flag
        result.append({
            "sub_hypothesis_id": sub_id,
            "title": title,
            "scientific_object": scientific_object,
            "inputs": inputs,
            "outcomes": outcomes,
            "comparison": comparison,
            "boundary": boundary,
            "causal_chain": _unique(_items(item.get("causal_chain"))),
            "reference_keys": [],
            "source_unit_ids": _collect_source_unit_ids(item),
            "source_record_ids": [f"sub_hypotheses:{sub_id}"],
        })
    known_ids = {item["sub_hypothesis_id"] for item in result}
    reference_map: dict[str, list[str]] = {
        _text(item.get("reference_key")): [
            item_id for item_id in _unique(_items(item.get("sub_hypothesis_ids"))) if item_id in known_ids
        ]
        for item in references
    }
    if len(result) == 1:
        only_id = result[0]["sub_hypothesis_id"]
        for reference_key, ids in reference_map.items():
            if not ids:
                reference_map[reference_key] = [only_id]
    for subhypothesis in result:
        subhypothesis["reference_keys"] = [
            reference["reference_key"] for reference in references
            if subhypothesis["sub_hypothesis_id"] in reference_map.get(reference["reference_key"], [])
        ]
        subhypothesis["source_unit_ids"] = _unique(
            _items(subhypothesis.get("source_unit_ids"))
            + _source_units_for_references(subhypothesis["reference_keys"], references)
        )
    return result, pending


def _reference_keys(values: Any, aliases: dict[str, str]) -> list[str]:
    keys: list[str] = []
    for value in _items(values):
        text = _text(value)
        if text in aliases:
            keys.append(aliases[text])
    return _unique(keys)


def _source_units_for_references(reference_keys: list[str], catalog: list[dict[str, Any]]) -> list[str]:
    by_key = {str(item.get("reference_key")): item for item in catalog if isinstance(item, dict)}
    return _unique([
        unit
        for key in reference_keys
        for unit in _items(_mapping(by_key.get(key)).get("source_unit_ids"))
    ])


def _source_records_for_references(reference_keys: list[str], catalog: list[dict[str, Any]]) -> list[str]:
    by_key = {str(item.get("reference_key")): item for item in catalog if isinstance(item, dict)}
    return _unique([
        record_id
        for key in reference_keys
        for record_id in _items(_mapping(by_key.get(key)).get("source_record_ids"))
    ])


def _gap_availability(gap: dict[str, Any]) -> tuple[str, bool, str]:
    readiness = _mapping(gap.get("causal_readiness"))
    joined = " ".join(
        _unique([
            gap.get("status"), gap.get("causal_status"), gap.get("gap_track"),
            gap.get("socrates_retrieval_mode"),
            *readiness.keys(), *[str(value) for value in readiness.values()],
        ])
    ).upper()
    restricted = bool(
        gap.get("restricted_component_bridge_hypothesis_allowed") is True
        or gap.get("component_bridge_gap_ready") is True
        or "COMPONENT_BRIDGE" in joined
    )
    direct = bool(
        gap.get("eligible_for_hypothesis_generation") is True
        or gap.get("direct_core") is True
        or "DIRECT_CORE" in joined
        or "CAUSAL_CHAIN_VALID" in joined
    )
    invalid = bool("INPUT_INVALID" in joined or gap.get("eligible_for_hypothesis_generation") is False)
    if restricted:
        return "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE", True, "restricted component/bridge evidence only"
    if direct and not invalid:
        return "AVAILABLE_DIRECT", True, "directly admissible evidence path"
    if invalid:
        return "UNAVAILABLE", False, "input or readiness gate is not satisfied"
    return "NEEDS_ENRICHMENT", False, "requires further evidence or readiness enrichment"


def _normalize_gaps(
    project: dict[str, Any], aliases: dict[str, str], references_catalog: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    gaps: list[dict[str, Any]] = []
    pending = False
    for index, raw in enumerate((item for item in _items(project.get("knowledge_gaps")) if isinstance(item, dict)), start=1):
        gap = _mapping(raw)
        gap_id = _first(gap.get("gap_id"), gap.get("id"), f"gap_{index}")
        description, flag = _english_or_placeholder(
            _first(gap.get("description"), gap.get("suggested_research_path"), gap.get("value_argument")),
            field=f"description for {gap_id}",
        )
        pending = pending or flag
        status, usable, scope = _gap_availability(gap)
        bundle = _mapping(gap.get("mechanism_evidence_bundle"))
        reference_keys = _reference_keys(
            _items(gap.get("supporting_references"))
            + _items(gap.get("source_evidence_ids"))
            + _items(bundle.get("direct_evidence_ids")),
            aliases,
        )
        source_unit_ids = _unique(
            _collect_source_unit_ids(gap)
            + _source_units_for_references(reference_keys, references_catalog)
        )
        source_record_ids = _unique(
            [f"knowledge_gaps:{gap_id}"]
            + _source_records_for_references(reference_keys, references_catalog)
        )
        raw_disclaimer = _first(gap.get("final_object_claim_disclaimer"), bundle.get("final_object_claim_disclaimer"))
        disclaimer, flag = _english_or_placeholder(
            raw_disclaimer,
            field=f"scope disclaimer for {gap_id}",
        )
        if status == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" and (not raw_disclaimer or flag):
            disclaimer = RESTRICTED_BRIDGE_DISCLAIMER
        elif not raw_disclaimer:
            disclaimer = ""
        pending = pending or flag
        gap_type, type_pending = _english_or_placeholder(
            _first(gap.get("gap_type"), gap.get("gap_track"), "knowledge gap"), field=f"type for {gap_id}"
        )
        pending = pending or type_pending
        causal_fields: dict[str, str] = {}
        for field, value in {
            "input": _first(bundle.get("intervention"), bundle.get("input")),
            "mediator": _first(bundle.get("mediator"), bundle.get("proposed_mediator")),
            "outcome": _first(bundle.get("outcome"), bundle.get("output")),
            "comparison": _first(bundle.get("comparison"), gap.get("comparison")),
            "falsification": _first(bundle.get("falsification"), gap.get("falsification")),
            "next_action": _first(gap.get("next_action"), gap.get("suggested_research_path")),
        }.items():
            rendered, field_pending = _english_or_placeholder(value, field=f"{field} for {gap_id}")
            # An explicit TBD/unknown marker remains auditable through the model
            # validation record, but never becomes a displayed causal fact.
            causal_fields[field] = rendered if value and not _is_unresolved_value(value) else ""
            pending = pending or field_pending
        gaps.append({
            "gap_id": gap_id,
            "sub_hypothesis_id": _first(gap.get("sub_hypothesis_id"), bundle.get("sub_hypothesis_id")),
            "gap_type": gap_type,
            "description": description,
            "availability": status,
            "usable_for_hypothesis_generation": usable,
            "scope": scope,
            "reference_keys": reference_keys,
            "source_unit_ids": source_unit_ids,
            "source_record_ids": source_record_ids,
            "input": causal_fields["input"],
            "mediator": causal_fields["mediator"],
            "outcome": causal_fields["outcome"],
            "comparison": causal_fields["comparison"],
            "falsification": causal_fields["falsification"],
            "disclaimer": disclaimer,
            "next_action": causal_fields["next_action"],
            "created_at": gap.get("createdAt") or gap.get("created_at") or "",
        })
    return gaps, pending


def _package_gap_ids(package: dict[str, Any]) -> list[str]:
    values: list[Any] = [package.get("primary_gap_id")]
    for key in ("gap_ids", "member_gap_ids", "source_gap_ids", "competing_mechanism_gap_ids"):
        values.extend(_items(package.get(key)))
    return _unique(values)


def _normalize_combination_gaps(project: dict[str, Any], gaps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    existing_gap_ids = {gap["gap_id"] for gap in gaps}
    gap_by_id = {gap["gap_id"]: gap for gap in gaps}
    result: list[dict[str, Any]] = []
    pending = False
    for index, raw in enumerate((item for item in _items(project.get("hypothesis_packages")) if isinstance(item, dict)), start=1):
        package = _mapping(raw)
        declared_gap_ids = _package_gap_ids(package)
        gap_ids = [gap_id for gap_id in declared_gap_ids if gap_id in existing_gap_ids]
        unknown_gap_ids = [gap_id for gap_id in declared_gap_ids if gap_id not in existing_gap_ids]
        package_type = _first(package.get("package_type"), package.get("track"), package.get("status"))
        is_combined = len(declared_gap_ids) >= 2 or "COMBIN" in package_type.upper() or "CROSS_SH" in package_type.upper()
        if not is_combined:
            continue
        package_id = _first(package.get("hypothesis_package_id"), package.get("package_id"), f"combined_gap_{index}")
        description, flag = _english_or_placeholder(
            _first(package.get("description"), package.get("research_question"), package.get("scope")),
            field=f"description for combined gap {package_id}",
        )
        pending = pending or flag
        gate = _mapping(package.get("coverage_and_compatibility_gate"))
        compatibility = _mapping(package.get("compatibility_audit"))
        gate_passed = bool(
            gate.get("ready") is True
            or compatibility.get("compatible") is True
            or _text(compatibility.get("verdict")).upper() == "PASS"
        )
        compatible = bool(len(declared_gap_ids) >= 2 and not unknown_gap_ids and len(gap_ids) >= 2 and gate_passed)
        status = "COMBINABLE" if compatible else "NOT_COMBINABLE"
        scope = _mapping(package.get("conclusion_scope"))
        disclaimer, flag = _english_or_placeholder(package.get("final_object_claim_disclaimer"), field="combined-gap disclaimer")
        if not _text(package.get("final_object_claim_disclaimer")):
            disclaimer = ""
        pending = pending or flag
        compatibility_reason, reason_pending = _english_or_placeholder(
            _first(
                compatibility.get("reason"), "; ".join(_unique(_items(gate.get("reasons")))),
                "No compatibility rationale was recorded.",
            ),
            field=f"compatibility rationale for {package_id}",
        )
        pending = pending or reason_pending
        result.append({
            "combined_gap_id": package_id,
            "declared_gap_ids": declared_gap_ids,
            "gap_ids": gap_ids,
            "unknown_gap_ids": unknown_gap_ids,
            "description": description,
            "status": status,
            "compatibility_gate_passed": gate_passed,
            "compatibility_reason": compatibility_reason,
            "allowed_scope": _unique(_items(scope.get("allowed"))),
            "forbidden_scope": _unique(_items(scope.get("forbidden"))),
            "disclaimer": disclaimer,
            "source_unit_ids": _unique([
                unit for gap_id in gap_ids for unit in _items(gap_by_id[gap_id].get("source_unit_ids"))
            ] + _collect_source_unit_ids(package)),
            "source_record_ids": _unique(
                [f"hypothesis_packages:{package_id}"]
                + [record_id for gap_id in gap_ids for record_id in _items(gap_by_id[gap_id].get("source_record_ids"))]
            ),
        })
    return result, pending


def _normalize_hypotheses(
    project: dict[str, Any], aliases: dict[str, str], gaps: list[dict[str, Any]], references_catalog: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    gap_by_id = {gap["gap_id"]: gap for gap in gaps}
    raw_items = [item for item in _items(project.get("hypotheses")) if isinstance(item, dict)]
    raw_items.extend(
        _mapping(item).get("idea_json")
        for item in _items(project.get("mingli_draft_ideas"))
        if isinstance(item, dict) and isinstance(_mapping(item).get("idea_json"), dict)
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    pending = False
    for index, raw in enumerate(raw_items, start=1):
        hypothesis = _mapping(raw)
        hypothesis_id = _first(hypothesis.get("hypothesis_id"), hypothesis.get("draft_idea_id"), hypothesis.get("idea_id"), f"hypothesis_{index}")
        if hypothesis_id in seen:
            continue
        seen.add(hypothesis_id)
        statement, flag = _english_or_placeholder(
            _first(hypothesis.get("statement"), hypothesis.get("hypothesis")),
            field=f"statement for {hypothesis_id}",
        )
        pending = pending or flag
        gap_id = _first(hypothesis.get("gap_id"), hypothesis.get("primary_gap_id"))
        package = _mapping(hypothesis.get("hypothesis_package"))
        raw_disclaimer = _first(
            hypothesis.get("final_object_claim_disclaimer"), package.get("final_object_claim_disclaimer"),
            gap_by_id.get(gap_id, {}).get("disclaimer"),
        )
        disclaimer, flag = _english_or_placeholder(
            raw_disclaimer,
            field=f"scope disclaimer for {hypothesis_id}",
        )
        if gap_by_id.get(gap_id, {}).get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" and (not raw_disclaimer or flag):
            disclaimer = RESTRICTED_BRIDGE_DISCLAIMER
        elif not raw_disclaimer:
            disclaimer = ""
        pending = pending or flag
        protocol = _mapping(hypothesis.get("experimental_protocol"))
        protocol_validation = _mapping(hypothesis.get("experimental_protocol_validation"))
        mechanism, mechanism_pending = _english_or_placeholder(
            _first(hypothesis.get("mechanism"), hypothesis.get("abstract")),
            field=f"mechanism for {hypothesis_id}",
        )
        expected_value, expected_pending = _english_or_placeholder(
            _first(hypothesis.get("expected_value"), hypothesis.get("related_work")),
            field=f"expected value for {hypothesis_id}",
        )
        test_plan, test_pending = _english_or_placeholder(
            _first(hypothesis.get("test_plan")), field=f"test plan for {hypothesis_id}"
        )
        pending = pending or mechanism_pending or expected_pending or test_pending
        reference_keys = _reference_keys(
            _items(hypothesis.get("supporting_references")) + _items(hypothesis.get("source_evidence_ids")), aliases
        ) or list(gap_by_id.get(gap_id, {}).get("reference_keys") or [])
        source_unit_ids = _unique(
            _collect_source_unit_ids(hypothesis)
            + _items(gap_by_id.get(gap_id, {}).get("source_unit_ids"))
            + _source_units_for_references(reference_keys, references_catalog)
        )
        source_record_ids = _unique(
            [f"hypotheses:{hypothesis_id}"]
            + _items(gap_by_id.get(gap_id, {}).get("source_record_ids"))
            + _source_records_for_references(reference_keys, references_catalog)
        )
        result.append({
            "hypothesis_id": hypothesis_id,
            "gap_id": gap_id,
            "sub_hypothesis_id": _first(hypothesis.get("sub_hypothesis_id"), gap_by_id.get(gap_id, {}).get("sub_hypothesis_id")),
            "status": _first(hypothesis.get("status"), "draft"),
            "statement": statement,
            "mechanism": mechanism if _first(hypothesis.get("mechanism"), hypothesis.get("abstract")) else "",
            "expected_value": expected_value if _first(hypothesis.get("expected_value"), hypothesis.get("related_work")) else "",
            "test_plan": test_plan if _first(hypothesis.get("test_plan")) else "",
            "disclaimer": disclaimer,
            "reference_keys": reference_keys,
            "source_unit_ids": source_unit_ids,
            "source_record_ids": source_record_ids,
            "experimental_protocol": protocol,
            "experiment_planning_status": _first(hypothesis.get("experiment_planning_status")),
            "experiment_authorized": protocol_validation.get("hard_gate_passed") is True and hypothesis.get("experiment_execution_status") == "authorized",
            "created_at": hypothesis.get("createdAt") or hypothesis.get("created_at") or "",
        })
    return result, pending


def _normalize_iterations(project: dict[str, Any], references: list[dict[str, Any]], gaps: list[dict[str, Any]], hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for subhypothesis in _items(project.get("sub_hypotheses")):
        if isinstance(subhypothesis, dict):
            events.append({
                "stage": "Subhypothesis decomposition",
                "identifier": _first(subhypothesis.get("id"), subhypothesis.get("sub_hypothesis_id")),
                "outcome": "A scoped subhypothesis was registered for evidence mapping.",
                "timestamp": subhypothesis.get("createdAt") or "",
                "source_unit_ids": _collect_source_unit_ids(subhypothesis),
                "source_record_ids": [f"sub_hypotheses:{_first(subhypothesis.get('id'), subhypothesis.get('sub_hypothesis_id'))}"],
            })
    for reference in references:
        events.append({
            "stage": "Literature ingestion",
            "identifier": reference["reference_key"],
            "outcome": "A literature record was retained in the frozen evidence catalogue.",
            "timestamp": "",
            "source_unit_ids": reference.get("source_unit_ids", []),
            "source_record_ids": reference.get("source_record_ids", []),
        })
    for gap in gaps:
        events.append({
            "stage": "TanXi gap analysis",
            "identifier": gap["gap_id"],
            "outcome": f"Gap status: {gap['availability']}.",
            "timestamp": gap.get("created_at") or "",
            "source_unit_ids": gap.get("source_unit_ids", []),
            "source_record_ids": gap.get("source_record_ids", []),
        })
    for report in _items(project.get("socrates_reports")):
        if isinstance(report, dict):
            events.append({
                "stage": "Socrates evidence enrichment",
                "identifier": _first(report.get("gap_id"), report.get("hypothesis_id"), "Socrates"),
                "outcome": _first(report.get("next_step"), report.get("verdict"), report.get("contract_status"), "Evidence enrichment was recorded."),
                "timestamp": report.get("createdAt") or report.get("created_at") or "",
                "source_unit_ids": _collect_source_unit_ids(report),
                "source_record_ids": [f"socrates_reports:{_first(report.get('gap_id'), report.get('hypothesis_id'), 'report')}"],
            })
    for hypothesis in hypotheses:
        events.append({
            "stage": "MingLi hypothesis generation",
            "identifier": hypothesis["hypothesis_id"],
            "outcome": f"Hypothesis status: {hypothesis['status']}.",
            "timestamp": hypothesis.get("created_at") or "",
            "source_unit_ids": hypothesis.get("source_unit_ids", []),
            "source_record_ids": hypothesis.get("source_record_ids", []),
        })
    for field, stage in (
        ("debate_reports", "Socrates debate"),
        ("verification_reports", "Verification"),
        ("yanzhen_reports", "YanZhen verification"),
    ):
        for ordinal, report in enumerate(_items(project.get(field)), start=1):
            if not isinstance(report, dict):
                continue
            events.append({
                "stage": stage,
                "identifier": _first(report.get("hypothesis_id"), report.get("gap_id"), f"{field}_{ordinal}"),
                "outcome": _first(report.get("next_step"), report.get("verdict"), report.get("status"), "A workflow record was retained."),
                "timestamp": report.get("createdAt") or report.get("created_at") or "",
                "source_unit_ids": _collect_source_unit_ids(report),
                "source_record_ids": [f"{field}:{ordinal}"],
            })
    def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        raw = item.get("timestamp")
        numeric = int(float(raw)) if isinstance(raw, (int, float)) else 0
        return numeric, _text(raw), _text(item.get("identifier"))
    normalized: list[dict[str, Any]] = []
    for event in sorted(events, key=sort_key):
        identifier, _ = _english_or_placeholder(event.get("identifier"), field="iteration artifact identifier")
        outcome, _ = _english_or_placeholder(event.get("outcome"), field="iteration outcome")
        normalized.append({**event, "identifier": identifier, "outcome": outcome})
    return normalized


def _build_claim_evidence_ledger(
    project: dict[str, Any],
    subhypotheses: list[dict[str, Any]],
    references: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    combined_gaps: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    iterations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the auditable claim-to-source ledger used by prose and validation."""
    ledger: list[dict[str, Any]] = [{
        "claim_id": "project_objective",
        "claim_kind": "project_metadata",
        "statement": _text(project.get("objective")),
        "certainty": "declared",
        "reference_keys": [],
        "source_unit_ids": _collect_source_unit_ids(project.get("objective")),
        "source_record_ids": ["project:objective"],
        "conclusion_scope": "project objective, not a result",
    }]
    for subhypothesis in subhypotheses:
        ledger.append({
            "claim_id": f"subhypothesis_{subhypothesis['sub_hypothesis_id']}",
            "claim_kind": "subhypothesis_definition",
            "statement": subhypothesis["title"],
            "certainty": "declared",
            "reference_keys": subhypothesis["reference_keys"],
            "source_unit_ids": subhypothesis.get("source_unit_ids", []),
            "source_record_ids": subhypothesis.get("source_record_ids", []),
            "conclusion_scope": "declared research unit, not a result",
        })
    for reference in references:
        ledger.append({
            "claim_id": f"source_{reference['reference_key']}",
            "claim_kind": "literature_record",
            "statement": reference["title"],
            "certainty": "source_catalogued",
            "reference_keys": [reference["reference_key"]],
            "source_unit_ids": reference.get("source_unit_ids", []),
            "source_record_ids": reference.get("source_record_ids", []),
            "conclusion_scope": "catalogued source record only",
        })
    for gap in gaps:
        ledger.append({
            "claim_id": f"gap_{gap['gap_id']}",
            "claim_kind": "evidence_gap",
            "statement": gap["description"],
            "certainty": "gap_assessment",
            "reference_keys": gap["reference_keys"],
            "source_unit_ids": gap.get("source_unit_ids", []),
            "source_record_ids": gap.get("source_record_ids", []),
            "conclusion_scope": gap["scope"],
        })
    for combined in combined_gaps:
        combined_reference_keys = _unique([
            key for gap in gaps if gap.get("gap_id") in _items(combined.get("gap_ids"))
            for key in _items(gap.get("reference_keys"))
        ])
        ledger.append({
            "claim_id": f"combined_gap_{combined['combined_gap_id']}",
            "claim_kind": "combined_gap_assessment",
            "statement": combined["description"],
            "certainty": "compatibility_assessment",
            "reference_keys": combined_reference_keys,
            "source_unit_ids": combined.get("source_unit_ids", []),
            "source_record_ids": combined.get("source_record_ids", []),
            "conclusion_scope": (
                "combined proposal is permitted only under the recorded compatibility gate"
                if combined.get("status") == "COMBINABLE" else "not a permitted combined gap"
            ),
        })
    for hypothesis in hypotheses:
        ledger.append({
            "claim_id": f"hypothesis_{hypothesis['hypothesis_id']}",
            "claim_kind": "hypothesis",
            "statement": hypothesis["statement"],
            "certainty": "hypothetical",
            "reference_keys": hypothesis["reference_keys"],
            "source_unit_ids": hypothesis.get("source_unit_ids", []),
            "source_record_ids": hypothesis.get("source_record_ids", []),
            "conclusion_scope": hypothesis["disclaimer"] or "proposal requiring subsequent testing",
        })
    for ordinal, event in enumerate(iterations, start=1):
        ledger.append({
            "claim_id": f"iteration_{ordinal}_{_safe_identifier(event.get('identifier'), 'event')}",
            "claim_kind": "workflow_event",
            "statement": event.get("outcome", ""),
            "certainty": "workflow_recorded",
            "reference_keys": [],
            "source_unit_ids": _items(event.get("source_unit_ids")),
            "source_record_ids": _items(event.get("source_record_ids")) or [f"workflow:{event.get('stage', 'event')}"],
            "conclusion_scope": "recorded process state, not an experimental result",
        })
    return ledger


def _duplicate_identifiers(items: list[dict[str, Any]], field: str) -> list[str]:
    values = [_text(item.get(field)) for item in items if _text(item.get(field))]
    return sorted({value for value in values if values.count(value) > 1})


def _is_unresolved_value(value: Any) -> bool:
    text = _text(value)
    return bool(not text or _UNRESOLVED_VALUE_RE.search(text) or text.startswith("No "))


def _contains_unsafe_validation_overclaim(text: Any) -> bool:
    """Flag validation language only when it is asserted rather than explicitly negated."""
    for sentence in re.split(r"(?<=[.!?])\s+", _text(text)):
        if _UNSAFE_NARRATIVE_RE.search(sentence) and not re.search(
            r"\b(?:not|never|without|rather than|does not|do not|must not|isn't|is not|aren't|are not)\b",
            sentence,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def _unresolved_model_fields(model: dict[str, Any]) -> list[dict[str, str]]:
    unresolved: list[dict[str, str]] = []
    project = _mapping(model.get("project"))
    for field in ("title", "objective", "domain", "research_mode"):
        if _is_unresolved_value(project.get(field)):
            unresolved.append({"entity": "project", "field": field, "value": _text(project.get(field))})
    for section_name, identifier, fields in (
        ("sub_hypotheses", "sub_hypothesis_id", ("scientific_object", "comparison", "boundary")),
        ("gaps", "gap_id", ("description", "input", "mediator", "outcome", "comparison")),
        ("hypotheses", "hypothesis_id", ("statement",)),
    ):
        for item in _items(model.get(section_name)):
            if not isinstance(item, dict):
                continue
            for field in fields:
                if _is_unresolved_value(item.get(field)):
                    unresolved.append({
                        "entity": f"{section_name}:{_text(item.get(identifier))}",
                        "field": field,
                        "value": _text(item.get(field)),
                    })
    return unresolved


def validate_research_report_model(model: dict[str, Any]) -> dict[str, Any]:
    """Audit identifier chains, evidence provenance, scope, and unresolved fields."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    references = [item for item in _items(model.get("references")) if isinstance(item, dict)]
    subhypotheses = [item for item in _items(model.get("sub_hypotheses")) if isinstance(item, dict)]
    gaps = [item for item in _items(model.get("gaps")) if isinstance(item, dict)]
    combined_gaps = [item for item in _items(model.get("combined_gaps")) if isinstance(item, dict)]
    hypotheses = [item for item in _items(model.get("hypotheses")) if isinstance(item, dict)]
    keys = [_text(item.get("reference_key")) for item in references]
    known_keys = set(keys)
    sh_ids = {_text(item.get("sub_hypothesis_id")) for item in subhypotheses}
    gap_ids = {_text(item.get("gap_id")) for item in gaps}
    if len(keys) != len(set(keys)):
        errors.append({"code": "DUPLICATE_REFERENCE_KEY", "detail": keys})
    for items, field, code in (
        (subhypotheses, "sub_hypothesis_id", "DUPLICATE_SUBHYPOTHESIS_ID"),
        (gaps, "gap_id", "DUPLICATE_GAP_ID"),
        (combined_gaps, "combined_gap_id", "DUPLICATE_COMBINED_GAP_ID"),
        (hypotheses, "hypothesis_id", "DUPLICATE_HYPOTHESIS_ID"),
    ):
        duplicates = _duplicate_identifiers(items, field)
        if duplicates:
            errors.append({"code": code, "detail": duplicates})
    for reference in references:
        if not _items(reference.get("source_unit_ids")):
            errors.append({"code": "REFERENCE_SOURCE_UNIT_MISSING", "detail": reference.get("reference_key")})
        if not _items(reference.get("source_record_ids")):
            errors.append({"code": "REFERENCE_RECORD_PROVENANCE_MISSING", "detail": reference.get("reference_key")})
        if int(reference.get("deduplicated_record_count") or 1) > 1 and not _items(reference.get("source_paper_ids")):
            errors.append({"code": "DEDUPLICATED_REFERENCE_LINEAGE_MISSING", "detail": reference.get("reference_key")})
    for gap in gaps:
        gap_id = _text(gap.get("gap_id"))
        if gap.get("sub_hypothesis_id") and gap.get("sub_hypothesis_id") not in sh_ids:
            errors.append({"code": "GAP_SUBHYPOTHESIS_ID_UNKNOWN", "detail": gap_id})
        if gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" and not gap.get("disclaimer"):
            errors.append({"code": "RESTRICTED_GAP_DISCLAIMER_MISSING", "detail": gap_id})
        unknown_refs = [key for key in _items(gap.get("reference_keys")) if key not in known_keys]
        if unknown_refs:
            errors.append({"code": "GAP_REFERENCE_KEY_UNKNOWN", "detail": {"gap_id": gap_id, "keys": unknown_refs}})
        if gap.get("reference_keys") and not _items(gap.get("source_unit_ids")):
            errors.append({"code": "GAP_SOURCE_UNIT_MISSING", "detail": gap_id})
    for combined in combined_gaps:
        combined_id = _text(combined.get("combined_gap_id"))
        declared = _unique(_items(combined.get("declared_gap_ids")))
        unknown = _unique(_items(combined.get("unknown_gap_ids")))
        if combined.get("status") == "COMBINABLE":
            if len(declared) < 2 or unknown or not combined.get("compatibility_gate_passed"):
                errors.append({"code": "FORCED_COMBINED_GAP", "detail": combined_id})
            if any(gap_id not in gap_ids for gap_id in _items(combined.get("gap_ids"))):
                errors.append({"code": "COMBINED_GAP_ID_UNKNOWN", "detail": combined_id})
        elif unknown:
            warnings.append({"code": "COMBINED_GAP_HAS_UNKNOWN_CONSTITUENTS", "detail": {"combined_gap_id": combined_id, "gap_ids": unknown}})
    for hypothesis in hypotheses:
        hypothesis_id = _text(hypothesis.get("hypothesis_id"))
        gap_id = _text(hypothesis.get("gap_id"))
        linked_gap = next((gap for gap in gaps if _text(gap.get("gap_id")) == gap_id), None)
        if gap_id and linked_gap is None:
            errors.append({"code": "HYPOTHESIS_GAP_NOT_IN_REPORT_SCOPE", "detail": hypothesis_id})
        if linked_gap and hypothesis.get("sub_hypothesis_id") and hypothesis.get("sub_hypothesis_id") != linked_gap.get("sub_hypothesis_id"):
            errors.append({"code": "HYPOTHESIS_SUBHYPOTHESIS_CHAIN_MISMATCH", "detail": hypothesis_id})
        if linked_gap and linked_gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" and not hypothesis.get("disclaimer"):
            errors.append({"code": "RESTRICTED_HYPOTHESIS_DISCLAIMER_MISSING", "detail": hypothesis_id})
        unknown_refs = [key for key in _items(hypothesis.get("reference_keys")) if key not in known_keys]
        if unknown_refs:
            errors.append({"code": "HYPOTHESIS_REFERENCE_KEY_UNKNOWN", "detail": {"hypothesis_id": hypothesis_id, "keys": unknown_refs}})
        if hypothesis.get("reference_keys") and not _items(hypothesis.get("source_unit_ids")):
            errors.append({"code": "HYPOTHESIS_SOURCE_UNIT_MISSING", "detail": hypothesis_id})
    for subhypothesis in subhypotheses:
        sh_id = _text(subhypothesis.get("sub_hypothesis_id"))
        related_gaps = [gap for gap in gaps if gap.get("sub_hypothesis_id") == sh_id]
        if not _items(subhypothesis.get("reference_keys")):
            warnings.append({"code": "SUBHYPOTHESIS_LITERATURE_COVERAGE_MISSING", "detail": sh_id})
        if not related_gaps:
            warnings.append({"code": "SUBHYPOTHESIS_GAP_COVERAGE_MISSING", "detail": sh_id})
    ledger = [item for item in _items(model.get("claim_evidence_ledger")) if isinstance(item, dict)]
    for claim in ledger:
        claim_id = _text(claim.get("claim_id"))
        if not _items(claim.get("source_record_ids")):
            errors.append({"code": "CLAIM_RECORD_PROVENANCE_MISSING", "detail": claim_id})
        if _items(claim.get("reference_keys")) and not _items(claim.get("source_unit_ids")):
            errors.append({"code": "CLAIM_SOURCE_UNIT_MISSING", "detail": claim_id})
    unresolved = _unresolved_model_fields(model)
    if unresolved:
        warnings.append({"code": "UNRESOLVED_FIELDS_RETAINED_AS_LIMITATIONS", "detail": unresolved})
    if not subhypotheses:
        warnings.append({"code": "NO_SUBHYPOTHESES", "detail": "The report will use project-level sections only."})
    if not references:
        warnings.append({"code": "NO_REFERENCES", "detail": "No PaperGraph records were available in the frozen snapshot."})
    if model.get("translation_pending"):
        warnings.append({"code": "ENGLISH_TRANSLATION_PENDING", "detail": "Source fields containing CJK text require a source-grounded English rendering."})
    return {
        "verdict": "PASS" if not errors else "REJECT",
        "errors": errors,
        "warnings": warnings,
        "coverage": {
            "subhypothesis_ids": sorted(sh_ids),
            "gap_ids": sorted(gap_ids),
            "hypothesis_ids": sorted(_text(item.get("hypothesis_id")) for item in hypotheses),
            "unresolved_fields": unresolved,
        },
    }


def _build_research_status(
    snapshot: dict[str, Any], gaps: list[dict[str, Any]], hypotheses: list[dict[str, Any]], iterations: list[dict[str, Any]]
) -> dict[str, Any]:
    gap_status_counts: dict[str, int] = {}
    for gap in gaps:
        status = _text(gap.get("availability")) or "UNCLASSIFIED"
        gap_status_counts[status] = gap_status_counts.get(status, 0) + 1
    hypothesis_status_counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        status = _text(hypothesis.get("status")) or "draft"
        hypothesis_status_counts[status] = hypothesis_status_counts.get(status, 0) + 1
    workflow_state = _first(
        snapshot.get("workflow_state"), snapshot.get("project_state"), snapshot.get("status"), "not recorded"
    )
    return {
        "recorded_workflow_state": workflow_state,
        "state_version": snapshot.get("state_version") or "not recorded",
        "gap_status_counts": gap_status_counts,
        "hypothesis_status_counts": hypothesis_status_counts,
        "workflow_event_count": len(iterations),
        "final_object_validation_status": "not claimed by this report",
        "restriction_policy": "predictions and hypotheses are not reported as experimental results",
    }


def _report_model_hash(model: dict[str, Any]) -> str:
    stable = deepcopy(model)
    stable.pop("generated_at", None)
    stable.pop("report_model_hash", None)
    return _canonical_hash(stable)


def build_research_report_model(project: dict[str, Any], *, report_id: str = "") -> dict[str, Any]:
    """Freeze an arbitrary science project into a domain-neutral report model."""
    snapshot = deepcopy(_mapping(project))
    project_id = _first(snapshot.get("project_id"), "unspecified_project")
    references, aliases, pending_references = _reference_catalog(snapshot.get("papergraph"))
    subhypotheses, pending_subhypotheses = _normalize_subhypotheses(snapshot, references)
    gaps, pending_gaps = _normalize_gaps(snapshot, aliases, references)
    combined_gaps, pending_combined = _normalize_combination_gaps(snapshot, gaps)
    hypotheses, pending_hypotheses = _normalize_hypotheses(snapshot, aliases, gaps, references)
    iterations = _normalize_iterations(snapshot, references, gaps, hypotheses)
    title, title_pending = _english_or_placeholder(
        _first(snapshot.get("title"), snapshot.get("objective"), project_id), field="project title"
    )
    objective, objective_pending = _english_or_placeholder(snapshot.get("objective"), field="project objective")
    domain, domain_pending = _english_or_placeholder(snapshot.get("domain"), field="research domain")
    snapshot_hash = _canonical_hash(snapshot)
    safe_report_id = _safe_identifier(report_id, f"report_{snapshot_hash[:12]}")
    research_mode, mode_pending = _english_or_placeholder(
        _first(snapshot.get("declared_research_mode"), snapshot.get("research_mode"), "not recorded"),
        field="research mode",
    )
    model = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_id": safe_report_id,
        "language": REPORT_LANGUAGE,
        "generated_at": _utc_now(),
        "project_snapshot_hash": snapshot_hash,
        "project_snapshot": snapshot,
        "project": {
            "project_id": project_id,
            "title": title,
            "domain": domain,
            "objective": objective,
            "research_mode": research_mode,
            "state_version": snapshot.get("state_version") or "",
        },
        "sub_hypotheses": subhypotheses,
        "references": references,
        "gaps": gaps,
        "combined_gaps": combined_gaps,
        "hypotheses": hypotheses,
        "iterations": iterations,
        "research_status": _build_research_status(snapshot, gaps, hypotheses, iterations),
        "translation_pending": any((
            pending_references, pending_subhypotheses, pending_gaps,
            pending_combined, pending_hypotheses, title_pending,
            objective_pending, domain_pending, mode_pending,
        )),
        "source_project_fields": {
            "papergraph_count": len(references),
            "papergraph_raw_record_count": len([item for item in _items(snapshot.get("papergraph")) if isinstance(item, dict)]),
            "sub_hypothesis_count": len(subhypotheses),
            "gap_count": len(gaps),
            "combined_gap_count": len(combined_gaps),
            "hypothesis_count": len(hypotheses),
        },
    }
    model["claim_evidence_ledger"] = _build_claim_evidence_ledger(
        snapshot, subhypotheses, references, gaps, combined_gaps, hypotheses, iterations
    )
    model["model_validation"] = validate_research_report_model(model)
    model["research_status"]["model_audit_verdict"] = model["model_validation"]["verdict"]
    model["research_status"]["unresolved_field_count"] = len(
        _items(_mapping(model["model_validation"].get("coverage")).get("unresolved_fields"))
    )
    model["report_model_hash"] = _report_model_hash(model)
    return model


def _latex_escape(value: Any) -> str:
    text = _text(value)
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _latex_citations(keys: list[str]) -> str:
    unique = _unique(keys)
    return f"~\\cite{{{','.join(unique)}}}" if unique else ""


def _latex_cell(value: Any, limit: int = 220) -> str:
    text = _text(value)
    if len(text) > limit:
        text = text[: max(0, limit - 3)].rstrip() + "..."
    return _latex_escape(text or "not recorded")


def _table(caption: str, label: str, headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    columns = "|".join("p{0.15\\textwidth}" for _ in headers)
    header = " & ".join(f"\\textbf{{{_latex_escape(item)}}}" for item in headers) + r" \\ \hline"
    body = "\n".join(" & ".join(row) + r" \\ \hline" for row in rows)
    return (
        "\\begin{table*}[t]\n\\centering\n\\scriptsize\n"
        f"\\caption{{{_latex_escape(caption)}}}\n\\label{{{_safe_identifier(label, 'table')}}}\n"
        f"\\begin{{tabular}}{{|{columns}|}}\n\\hline\n{header}\n{body}\n"
        "\\end{tabular}\n\\end{table*}\n"
    )


def _render_metadata(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    title = _latex_escape(project.get("title") or "Evidence-Bounded Research Traceability Report")
    return (
        f"\\title{{{title}\\\\\n"
        "{\\footnotesize English-only, evidence-traceable research process report}}\n"
        "\\author{\\IEEEauthorblockN{Research Traceability Report}\\n"
        "\\IEEEauthorblockA{Generated from a frozen AI-for-Science project snapshot\\\\\n"
        "Scientific claims retain their recorded evidence scope and validation status.}}\n"
        "\\maketitle\n"
    )


def _render_research_status(model: dict[str, Any]) -> str:
    status = _mapping(model.get("research_status"))
    validation = _mapping(model.get("model_validation"))
    coverage = _mapping(validation.get("coverage"))
    rows = [
        ["Recorded workflow state", _latex_cell(status.get("recorded_workflow_state"), 360)],
        ["Frozen state version", _latex_cell(status.get("state_version"), 360)],
        ["Model audit verdict", _latex_cell(status.get("model_audit_verdict"), 360)],
        ["Final-object validation", _latex_cell(status.get("final_object_validation_status"), 360)],
        ["Restriction policy", _latex_cell(status.get("restriction_policy"), 360)],
        ["Unresolved fields retained", _latex_cell(status.get("unresolved_field_count"), 360)],
    ]
    unresolved = _items(coverage.get("unresolved_fields"))
    content = ["\\section{Research Status and Scope Limitations}\\n"]
    content.append(_table(
        "Recorded project status and non-result scope declaration.", "tab:research_status",
        ["Status item", "Recorded value"], rows,
    ))
    content.append(
        "All gap classifications, hypotheses, and expected observations in this report are frozen workflow artifacts. "
        "They must not be interpreted as experimental findings or validation of a final research object.\\n"
    )
    if unresolved:
        content.append("\\subsection{Explicitly Unresolved Fields}\\n\\begin{itemize}\\n")
        for item in unresolved[:40]:
            if not isinstance(item, dict):
                continue
            content.append(
                f"\\item {_latex_escape(item.get('entity'))}: {_latex_escape(item.get('field'))} remains "
                "unresolved in the frozen snapshot and is not written as a confirmed fact.\\n"
            )
        content.append("\\end{itemize}\\n")
    return "".join(content)


def _render_abstract(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    counts = _mapping(model.get("source_project_fields"))
    restricted = [gap for gap in _items(model.get("gaps")) if isinstance(gap, dict) and gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE"]
    scope = (
        " Some candidate hypotheses are restricted to component or bridge evidence and are not claims that the final research object has been validated."
        if restricted else " Generated hypotheses remain proposals for subsequent testing rather than validated results."
    )
    return (
        "\\begin{abstract}\n"
        f"This English-only research traceability report addresses {_latex_escape(project.get('objective'))}. "
        f"The frozen project snapshot contains {counts.get('sub_hypothesis_count', 0)} subhypotheses, "
        f"{counts.get('papergraph_count', 0)} catalogued literature records, {counts.get('gap_count', 0)} identified gaps, "
        f"and {counts.get('hypothesis_count', 0)} generated hypotheses. "
        "It distinguishes source-supported findings, evidence gaps, hypothesis proposals, and planned validation activities. "
        "The report records per-subhypothesis literature coverage, reported limitations, admissible and restricted gaps, "
        "combined-gap compatibility, hypothesis evolution, and optional validation planning."
        f"{scope}\n\\end{{abstract}}\n"
        "\\begin{IEEEkeywords}\nresearch traceability, evidence synthesis, knowledge gaps, falsifiable hypotheses, literature review\n\\end{IEEEkeywords}\n"
    )


def _render_problem_and_subhypotheses(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    rows: list[list[str]] = []
    for item in _items(model.get("sub_hypotheses")):
        if not isinstance(item, dict):
            continue
        rows.append([
            _latex_cell(item.get("sub_hypothesis_id"), 60),
            _latex_cell(item.get("scientific_object"), 150),
            _latex_cell(_list_text(item.get("inputs")), 120),
            _latex_cell(_list_text(item.get("outcomes")), 120),
            _latex_cell(item.get("comparison"), 120),
        ])
    table = _table(
        "Subhypothesis decomposition in the frozen project snapshot.",
        "tab:subhypotheses",
        ["SH", "Scientific object", "Input or intervention", "Outcome", "Comparison"],
        rows,
    )
    return (
        "\\section{Research Objective and Subhypothesis Decomposition}\n"
        f"The project is situated in {_latex_escape(project.get('domain'))} and uses the recorded research mode "
        f"\\texttt{{{_latex_escape(project.get('research_mode'))}}}. The declared objective is "
        f"{_latex_escape(project.get('objective'))}. Subhypotheses are retained as separate evidence and reasoning units; "
        "their later combination is allowed only when an explicit compatibility record exists.\n"
        + table
    )


def _reference_sentence(reference: dict[str, Any]) -> str:
    fragments: list[str] = []
    if reference.get("scenario"):
        fragments.append(f"examines {_latex_escape(reference['scenario'])}")
    if reference.get("method"):
        fragments.append(f"using {_latex_escape(reference['method'])}")
    if reference.get("benchmark"):
        fragments.append(f"with {_latex_escape(reference['benchmark'])} recorded as a relevant outcome or benchmark")
    description = ", ".join(fragments) if fragments else "is retained as a mapped literature record"
    return f"The project record for {_latex_escape(reference['title'])} {description}{_latex_citations([reference['reference_key']])}."


def _render_literature_review(model: dict[str, Any]) -> str:
    references = {item.get("reference_key"): item for item in _items(model.get("references")) if isinstance(item, dict)}
    content = ["\\section{Multi-Subhypothesis Literature Review}\n"]
    for subhypothesis in _items(model.get("sub_hypotheses")):
        if not isinstance(subhypothesis, dict):
            continue
        sh_id = _latex_escape(subhypothesis.get("sub_hypothesis_id"))
        title = _latex_escape(subhypothesis.get("title"))
        content.append(f"\\subsection{{{sh_id}: {title}}}\n")
        keys = _unique(_items(subhypothesis.get("reference_keys")))
        if not keys:
            content.append(
                "No PaperGraph literature record was mapped to this subhypothesis in the frozen snapshot. "
                "This is a coverage limitation, not evidence that relevant research does not exist.\n"
            )
            continue
        content.append(
            f"This subsection contains {len(keys)} mapped literature record(s). The following statements describe only "
            "fields retained in the project evidence catalogue.\n"
        )
        for key in keys:
            reference = references.get(key)
            if reference:
                content.append(_reference_sentence(reference) + "\n")
    unassigned = [item for item in references.values() if not any(item.get("reference_key") in _items(sh.get("reference_keys")) for sh in _items(model.get("sub_hypotheses")) if isinstance(sh, dict))]
    if unassigned:
        content.append("\\subsection{Project-Level Literature Records}\n")
        content.append("The following records were retained at project level because no unique subhypothesis mapping was present.\n")
        for reference in unassigned:
            content.append(_reference_sentence(reference) + "\n")
    return "".join(content)


def _render_literature_matrix(model: dict[str, Any]) -> str:
    references = [item for item in _items(model.get("references")) if isinstance(item, dict)]
    if not references:
        return (
            "\\section{Literature Evidence Matrix}\\n"
            "No PaperGraph record was available in the frozen snapshot; this is a catalogue-coverage limitation rather than a claim about the field.\\n"
        )
    rows: list[list[str]] = []
    for reference in references:
        mapped_sh = ", ".join(_unique(_items(reference.get("sub_hypothesis_ids")))) or "project-level"
        rows.append([
            _latex_cell(reference.get("reference_key"), 105),
            _latex_cell(mapped_sh, 80),
            _latex_cell(reference.get("method"), 135),
            _latex_cell(reference.get("scenario"), 135),
            _latex_cell(reference.get("benchmark"), 125),
            _latex_cell(", ".join(_unique(_items(reference.get("source_unit_ids")))) or "missing", 120),
        ])
    return (
        "\\section{Literature Evidence Matrix}\\n"
        "This deterministic matrix exposes the extracted catalogue fields and source-unit provenance used in later report sections.\\n"
        + _table(
            "Mapped literature fields in the frozen evidence catalogue.", "tab:literature_matrix",
            ["Citation key", "Mapped SH", "Method", "Scenario", "Outcome/benchmark", "Source unit(s)"], rows,
        )
    )


def _render_limitations(model: dict[str, Any]) -> str:
    references = [item for item in _items(model.get("references")) if isinstance(item, dict)]
    content = ["\\section{Limitations of Existing Research and Current Evidence}\n"]
    content.append(
        "This section separates source-stated limitations from limitations of the current project evidence map. "
        "A missing extracted field is not treated as a claim that the underlying literature lacks that property.\n"
    )
    source_limitations: list[tuple[dict[str, Any], str]] = []
    for reference in references:
        for limitation in _items(reference.get("limitations")):
            source_limitations.append((reference, _text(limitation)))
    if source_limitations:
        content.append("\\subsection{Source-Stated Limitations}\n\\begin{itemize}\n")
        for reference, limitation in source_limitations[:30]:
            content.append(f"\\item {_latex_escape(limitation)}{_latex_citations([reference['reference_key']])}.\n")
        content.append("\\end{itemize}\n")
    else:
        content.append(
            "\\subsection{Source-Stated Limitations}\nNo explicit source-stated limitation was extracted into the frozen project snapshot. "
            "The report therefore makes no synthetic claim about a universal methodological limitation.\n"
        )
    content.append("\\subsection{Evidence-Map Limitations}\n\\begin{itemize}\n")
    for gap in _items(model.get("gaps")):
        if isinstance(gap, dict) and gap.get("availability") != "AVAILABLE_DIRECT":
            content.append(
                f"\\item Gap {_latex_escape(gap.get('gap_id'))} is currently classified as "
                f"\\texttt{{{_latex_escape(gap.get('availability'))}}}: {_latex_escape(gap.get('scope'))}.\n"
            )
    if not any(isinstance(gap, dict) and gap.get("availability") != "AVAILABLE_DIRECT" for gap in _items(model.get("gaps"))):
        content.append("\\item No non-direct or unresolved gap classification was retained in the current report scope.\n")
    content.append("\\end{itemize}\n")
    return "".join(content)


def _render_gaps(model: dict[str, Any]) -> str:
    rows: list[list[str]] = []
    content = ["\\section{Available Gaps by Subhypothesis}\n"]
    for gap in _items(model.get("gaps")):
        if not isinstance(gap, dict):
            continue
        references = _latex_citations(_unique(_items(gap.get("reference_keys"))))
        rows.append([
            _latex_cell(gap.get("gap_id"), 80),
            _latex_cell(gap.get("sub_hypothesis_id"), 55),
            _latex_cell(gap.get("gap_type"), 85),
            _latex_cell(gap.get("availability"), 110),
            _latex_cell(gap.get("description"), 250) + references,
        ])
    content.append(_table(
        "Gap status and scope. A gap is usable only when its displayed status permits hypothesis generation.",
        "tab:per_sh_gaps",
        ["Gap ID", "SH", "Type", "Availability", "Evidence-bounded description"],
        rows,
    ))
    for gap in _items(model.get("gaps")):
        if not isinstance(gap, dict) or not gap.get("usable_for_hypothesis_generation"):
            continue
        content.append(f"\\subsection{{{_latex_escape(gap.get('gap_id'))}}}\n")
        content.append(
            f"This gap is classified as \\texttt{{{_latex_escape(gap.get('availability'))}}}. "
            f"Its recorded causal fields are input: {_latex_escape(gap.get('input') or 'not resolved')}; "
            f"mediator: {_latex_escape(gap.get('mediator') or 'not resolved')}; "
            f"outcome: {_latex_escape(gap.get('outcome') or 'not resolved')}; and comparison: "
            f"{_latex_escape(gap.get('comparison') or 'not resolved')}.\n"
        )
        if gap.get("disclaimer"):
            content.append(f"\\textit{{Scope limitation: {_latex_escape(gap.get('disclaimer'))}}}\n")
    if not rows:
        content.append("No knowledge-gap record was available in the frozen project snapshot.\n")
    return "".join(content)


def _render_combined_gaps(model: dict[str, Any]) -> str:
    combinations = [item for item in _items(model.get("combined_gaps")) if isinstance(item, dict)]
    content = ["\\section{Combined Gaps Across Subhypotheses}\n"]
    if not combinations:
        return "".join(content) + (
            "No combined gap passed into the current report scope. The report does not construct a cross-subhypothesis "
            "causal claim merely by concatenating independent gaps.\n"
        )
    rows: list[list[str]] = []
    for combination in combinations:
        rows.append([
            _latex_cell(combination.get("combined_gap_id"), 100),
            _latex_cell(", ".join(_unique(_items(combination.get("gap_ids")))), 130),
            _latex_cell(combination.get("status"), 100),
            _latex_cell(combination.get("compatibility_reason"), 210),
            _latex_cell(combination.get("description"), 220),
        ])
    content.append(_table(
        "Compatibility assessment for cross-subhypothesis combined gaps.",
        "tab:combined_gaps",
        ["Combined ID", "Constituent gaps", "Status", "Compatibility rationale", "Question"],
        rows,
    ))
    for combination in combinations:
        if combination.get("disclaimer"):
            content.append(f"\\textit{{Scope limitation: {_latex_escape(combination.get('disclaimer'))}}}\n")
    return "".join(content)


def _render_hypotheses(model: dict[str, Any]) -> str:
    hypotheses = [item for item in _items(model.get("hypotheses")) if isinstance(item, dict)]
    content = ["\\section{Generated Hypotheses}\n"]
    if not hypotheses:
        return "".join(content) + "No MingLi hypothesis or retained hypothesis draft was present in the frozen project snapshot.\n"
    rows: list[list[str]] = []
    for hypothesis in hypotheses:
        rows.append([
            _latex_cell(hypothesis.get("hypothesis_id"), 95),
            _latex_cell(hypothesis.get("gap_id"), 90),
            _latex_cell(hypothesis.get("status"), 80),
            _latex_cell(hypothesis.get("statement"), 290) + _latex_citations(_unique(_items(hypothesis.get("reference_keys")))),
            _latex_cell("restricted" if hypothesis.get("disclaimer") else "proposal for testing", 100),
        ])
    content.append(_table(
        "Hypotheses are testable proposals rather than results.", "tab:hypotheses",
        ["Hypothesis ID", "Gap", "Status", "Statement", "Scope"], rows,
    ))
    for hypothesis in hypotheses:
        content.append(f"\\subsection{{{_latex_escape(hypothesis.get('hypothesis_id'))}}}\n")
        content.append(f"\\textbf{{Hypothesis.}} {_latex_escape(hypothesis.get('statement'))}\n")
        if hypothesis.get("mechanism"):
            content.append(f"\\textbf{{Recorded mechanism.}} {_latex_escape(hypothesis.get('mechanism'))}\n")
        if hypothesis.get("test_plan"):
            content.append(f"\\textbf{{Recorded test plan.}} {_latex_escape(hypothesis.get('test_plan'))}\n")
        if hypothesis.get("disclaimer"):
            content.append(f"\\textit{{Scope limitation: {_latex_escape(hypothesis.get('disclaimer'))}}}\n")
        else:
            content.append("\\textit{This hypothesis is a proposal for testing and is not reported as a validated result.}\n")
    return "".join(content)


def _render_iterations(model: dict[str, Any]) -> str:
    events = [item for item in _items(model.get("iterations")) if isinstance(item, dict)]
    content = ["\\section{Iterative Research Process}\n"]
    content.append(
        "The timeline below is a compact rendering of structured project artifacts. It does not infer unrecorded agent decisions or experiments.\n"
    )
    rows = [[
        _latex_cell(event.get("stage"), 150),
        _latex_cell(event.get("identifier"), 110),
        _latex_cell(event.get("outcome"), 310),
    ] for event in events]
    content.append(_table(
        "Research-process events recorded in the frozen snapshot.", "tab:iterations",
        ["Stage", "Artifact", "Recorded outcome"], rows,
    ))
    return "".join(content)


def _render_experiment_plan(model: dict[str, Any]) -> str:
    hypotheses = [item for item in _items(model.get("hypotheses")) if isinstance(item, dict)]
    content = ["\\section{Optional Feasible Validation Plans and Expected Discriminating Observations}\n"]
    authorized = [item for item in hypotheses if item.get("experiment_authorized")]
    if not authorized:
        return "".join(content) + (
            "No hypothesis in this frozen snapshot has an authorized executable protocol. The report therefore provides no claimed "
            "experimental result. Future work should test the stated comparison, mechanism, outcome, and falsification condition only "
            "after the applicable debate and protocol gates are satisfied.\n"
        )
    for hypothesis in authorized:
        protocol = _mapping(hypothesis.get("experimental_protocol"))
        content.append(f"\\subsection{{{_latex_escape(hypothesis.get('hypothesis_id'))}}}\n")
        content.append(
            "The following is a recorded plan, not an executed study. Expected observations are predictions that would distinguish "
            "the recorded hypothesis from alternatives.\n"
        )
        for label, key in (("Research question", "research_question"), ("Causal claim", "causal_claim")):
            if protocol.get(key):
                content.append(f"\\textbf{{{label}.}} {_latex_escape(protocol.get(key))}\n")
    return "".join(content)


def _render_conclusion(model: dict[str, Any]) -> str:
    counts = _mapping(model.get("source_project_fields"))
    usable = sum(1 for item in _items(model.get("gaps")) if isinstance(item, dict) and item.get("usable_for_hypothesis_generation"))
    combined = sum(1 for item in _items(model.get("combined_gaps")) if isinstance(item, dict) and item.get("status") == "COMBINABLE")
    return (
        "\\section{Conclusion and Next Steps}\n"
        f"The frozen snapshot contains {counts.get('sub_hypothesis_count', 0)} subhypotheses, {counts.get('papergraph_count', 0)} "
        f"literature records, {usable} currently usable gap(s), {combined} combinable cross-subhypothesis gap(s), and "
        f"{counts.get('hypothesis_count', 0)} hypothesis record(s). The next action should be determined by the recorded gap and "
        "hypothesis readiness states: targeted evidence enrichment for unresolved causal fields, constrained hypothesis refinement for "
        "admissible gaps, and protocol development only after the relevant verification gates permit it. This report does not convert "
        "a hypothesis, a bridge evidence package, or a planned observation into a validated final-object conclusion.\n"
    )


def _narrative_context(
    model: dict[str, Any], section_id: str
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    """Create a small, section-local evidence package; raw project logs never enter it."""
    references = [item for item in _items(model.get("references")) if isinstance(item, dict)]
    subhypotheses = [item for item in _items(model.get("sub_hypotheses")) if isinstance(item, dict)]
    gaps = [item for item in _items(model.get("gaps")) if isinstance(item, dict)]
    combined_gaps = [item for item in _items(model.get("combined_gaps")) if isinstance(item, dict)]
    hypotheses = [item for item in _items(model.get("hypotheses")) if isinstance(item, dict)]
    ledger = [item for item in _items(model.get("claim_evidence_ledger")) if isinstance(item, dict)]
    payload: dict[str, Any]
    claim_kinds: set[str]
    if section_id == "abstract":
        payload = {
            "project": _mapping(model.get("project")), "counts": _mapping(model.get("source_project_fields")),
            "research_status": _mapping(model.get("research_status")),
        }
        claim_kinds = {"project_metadata", "evidence_gap", "hypothesis"}
    elif section_id == "research_status":
        payload = {
            "research_status": _mapping(model.get("research_status")),
            "unresolved_fields": _mapping(_mapping(model.get("model_validation")).get("coverage")).get("unresolved_fields", []),
        }
        claim_kinds = {"project_metadata", "workflow_event"}
    elif section_id == "problem_and_sh":
        payload = {"project": _mapping(model.get("project")), "subhypotheses": subhypotheses}
        claim_kinds = {"project_metadata", "subhypothesis_definition"}
    elif section_id in {"literature_review", "literature_matrix"}:
        payload = {
            "subhypotheses": [
                {key: item.get(key) for key in ("sub_hypothesis_id", "title", "reference_keys")}
                for item in subhypotheses
            ],
            "references": [
                {key: item.get(key) for key in ("reference_key", "title", "method", "scenario", "benchmark", "source_unit_ids")}
                for item in references[:40]
            ],
        }
        claim_kinds = {"literature_record", "subhypothesis_definition"}
    elif section_id == "limitations":
        payload = {
            "source_limitations": [
                {"reference_key": item.get("reference_key"), "limitations": item.get("limitations")}
                for item in references[:40]
            ],
            "gaps": [{key: item.get(key) for key in ("gap_id", "availability", "scope", "disclaimer")} for item in gaps],
        }
        claim_kinds = {"literature_record", "evidence_gap"}
    elif section_id == "per_sh_gaps":
        payload = {"gaps": gaps, "subhypotheses": [{"sub_hypothesis_id": item.get("sub_hypothesis_id")} for item in subhypotheses]}
        claim_kinds = {"evidence_gap", "subhypothesis_definition"}
    elif section_id == "combined_gaps":
        payload = {"combined_gaps": combined_gaps, "gaps": [{key: item.get(key) for key in ("gap_id", "availability", "reference_keys")} for item in gaps]}
        claim_kinds = {"combined_gap_assessment", "evidence_gap"}
    elif section_id == "hypotheses":
        payload = {"hypotheses": hypotheses, "gaps": [{key: item.get(key) for key in ("gap_id", "availability", "disclaimer")} for item in gaps]}
        claim_kinds = {"hypothesis", "evidence_gap"}
    elif section_id == "iterations":
        payload = {"iterations": _items(model.get("iterations"))[:60]}
        claim_kinds = {"workflow_event"}
    elif section_id == "experimental_plan":
        payload = {"authorized_protocols": [
            {key: item.get(key) for key in ("hypothesis_id", "experimental_protocol", "experiment_authorized", "disclaimer")}
            for item in hypotheses if item.get("experiment_authorized")
        ]}
        claim_kinds = {"hypothesis"}
    elif section_id == "conclusion":
        payload = {"counts": _mapping(model.get("source_project_fields")), "research_status": _mapping(model.get("research_status"))}
        claim_kinds = {"project_metadata", "evidence_gap", "combined_gap_assessment", "hypothesis"}
    else:
        return {}, [], [], []
    claims = [
        {
            "claim_id": item.get("claim_id"), "claim_kind": item.get("claim_kind"),
            "certainty": item.get("certainty"), "reference_keys": item.get("reference_keys"),
            "source_unit_ids": item.get("source_unit_ids"), "conclusion_scope": item.get("conclusion_scope"),
        }
        for item in ledger if item.get("claim_kind") in claim_kinds
    ]
    allowed_keys = _unique([key for claim in claims for key in _items(claim.get("reference_keys"))])
    allowed_claim_ids = _unique([claim.get("claim_id") for claim in claims])
    scope_sensitive_sections = {"abstract", "research_status", "limitations", "per_sh_gaps", "combined_gaps", "hypotheses", "experimental_plan", "conclusion"}
    required_disclaimers = _unique([
        item.get("disclaimer") for item in gaps + hypotheses + combined_gaps if _text(item.get("disclaimer"))
    ]) if section_id in scope_sensitive_sections else []
    return {"facts": payload, "admissible_claims": claims}, allowed_keys, allowed_claim_ids, required_disclaimers


def _call_narrative_llm(
    *,
    section_id: str,
    context: dict[str, Any],
    allowed_keys: list[str],
    allowed_claim_ids: list[str],
    required_scope_disclaimers: list[str],
    prior_feedback: list[dict[str, Any]],
    llm_callable: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    if llm_callable is None:
        try:
            from ._llm import call_llm_json
        except ImportError:
            from _llm import call_llm_json
        llm_callable = call_llm_json
    response = llm_callable(
        system=(
            "You write an English-only research-report paragraph for any scientific or engineering discipline. "
            "You are a bounded prose renderer, not a source of scientific facts. Return JSON only. Use only the supplied "
            "snapshot facts. Do not introduce entities, methods, measurements, effect sizes, experimental results, citations, "
            "or causal conclusions that are absent from the input. Do not say that a final research object is proved, validated, "
            "or conclusively established. Every literature-derived factual sentence must cite one supplied key exactly as "
            "[[CITE:reference_key]]. Preserve any required scope disclaimer verbatim."
        ),
        prompt=(
            f"Write one concise paragraph for report section '{section_id}'. English only. "
            f"Allowed citation keys: {allowed_keys}. Allowed claim IDs: {allowed_claim_ids}. "
            f"Required scope disclaimers (verbatim if listed): {required_scope_disclaimers}. "
            "Repair every listed validation issue if prior feedback is present.\n\n"
            f"INPUT_JSON:\n{json.dumps({'context': context, 'prior_validation_feedback': prior_feedback[-10:]}, ensure_ascii=False, indent=2, default=str)[:22000]}\n\n"
            "Return exactly: {\"section_id\":\"...\",\"text\":\"...\",\"citation_keys\":[\"...\"],"
            "\"claim_ids\":[\"...\"],\"self_critique\":\"...\"}. Cite every literature-derived factual sentence with [[CITE:key]]."
        ),
        max_tokens=1100,
    )
    return response if isinstance(response, dict) else {}


def audit_report_narrative(
    proposal: dict[str, Any],
    *,
    section_id: str,
    allowed_keys: list[str],
    allowed_claim_ids: list[str],
    required_scope_disclaimers: list[str],
) -> dict[str, Any]:
    text = _text(proposal.get("text"))
    failures: list[dict[str, Any]] = []
    if _text(proposal.get("section_id")) != section_id:
        failures.append({"code": "NARRATIVE_SECTION_ID_MISMATCH", "detail": section_id})
    if len(text) < 80:
        failures.append({"code": "NARRATIVE_TOO_SHORT", "detail": len(text)})
    if _CJK_RE.search(text):
        failures.append({"code": "NARRATIVE_NOT_ENGLISH", "detail": "CJK characters detected"})
    if _contains_unsafe_validation_overclaim(text):
        failures.append({"code": "NARRATIVE_OVERCLAIMS_VALIDATION", "detail": "unsafe validation claim"})
    if _RESULT_OVERCLAIM_RE.search(text):
        failures.append({"code": "NARRATIVE_TREATS_PREDICTION_AS_RESULT", "detail": "observed-result language is not allowed"})
    cited = _unique(_CITATION_TOKEN_RE.findall(text))
    declared = _unique(_items(proposal.get("citation_keys")))
    unknown = [key for key in cited + declared if key not in set(allowed_keys)]
    if unknown:
        failures.append({"code": "NARRATIVE_UNKNOWN_CITATION", "detail": _unique(unknown)})
    if set(cited) != set(declared):
        failures.append({"code": "NARRATIVE_CITATION_DECLARATION_MISMATCH", "detail": {"text": cited, "declared": declared}})
    if allowed_keys and not cited:
        failures.append({"code": "NARRATIVE_EVIDENCE_CITATION_MISSING", "detail": allowed_keys})
    declared_claim_ids = _unique(_items(proposal.get("claim_ids")))
    unknown_claims = [claim_id for claim_id in declared_claim_ids if claim_id not in set(allowed_claim_ids)]
    if unknown_claims:
        failures.append({"code": "NARRATIVE_UNKNOWN_CLAIM_ID", "detail": unknown_claims})
    if allowed_claim_ids and not declared_claim_ids:
        failures.append({"code": "NARRATIVE_CLAIM_PROVENANCE_MISSING", "detail": allowed_claim_ids})
    for disclaimer in required_scope_disclaimers:
        if disclaimer not in text:
            failures.append({"code": "NARRATIVE_SCOPE_LIMITATION_MISSING", "detail": disclaimer})
    self_critique = _text(proposal.get("self_critique"))
    if len(self_critique) < _SELF_CRITIQUE_MIN_LENGTH or _CJK_RE.search(self_critique):
        failures.append({"code": "NARRATIVE_SELF_CRITIQUE_MISSING", "detail": "A substantive English self-critique is required."})
    return {
        "verdict": "PASS" if not failures else "REJECT",
        "hard_gate_passed": not failures,
        "failures": failures,
        "citation_keys": cited,
        "claim_ids": declared_claim_ids,
        "self_critique": self_critique,
        "text": text,
    }


def _narrative_to_latex(text: str) -> str:
    tokens: dict[str, str] = {}
    def replace(match: re.Match[str]) -> str:
        marker = f"REPORTCITE{len(tokens)}MARKER"
        tokens[marker] = _latex_citations([match.group(1)]).strip()
        return marker
    placeholder_text = _CITATION_TOKEN_RE.sub(replace, text)
    rendered = _latex_escape(placeholder_text)
    for marker, citation in tokens.items():
        rendered = rendered.replace(marker, citation)
    return rendered


def _refine_narrative_sections(
    model: dict[str, Any],
    sections: dict[str, str],
    *,
    llm_callable: Callable[..., dict[str, Any]] | None,
    max_retries: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    audits: dict[str, Any] = {}
    retries = max(0, min(MAX_NARRATIVE_RETRIES, int(max_retries or 0)))
    section_to_latex_key = {
        "abstract": "abstract",
        "research_status": "research_status",
        "problem_and_sh": "problem_and_sh",
        "literature_review": "literature_review",
        "literature_matrix": "literature_matrix",
        "limitations": "limitations",
        "per_sh_gaps": "per_sh_gaps",
        "combined_gaps": "combined_gaps",
        "hypotheses": "hypotheses",
        "iterations": "iterations",
        "experimental_plan": "experimental_plan",
        "conclusion": "conclusion",
    }
    for section_id, latex_key in section_to_latex_key.items():
        context, allowed_keys, allowed_claim_ids, required_scope_disclaimers = _narrative_context(model, section_id)
        if not context:
            continue
        feedback: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, retries + 2):
            try:
                proposal = _call_narrative_llm(
                    section_id=section_id,
                    context=context,
                    allowed_keys=allowed_keys,
                    allowed_claim_ids=allowed_claim_ids,
                    required_scope_disclaimers=required_scope_disclaimers,
                    prior_feedback=feedback,
                    llm_callable=llm_callable,
                )
                audit = audit_report_narrative(
                    proposal,
                    section_id=section_id,
                    allowed_keys=allowed_keys,
                    allowed_claim_ids=allowed_claim_ids,
                    required_scope_disclaimers=required_scope_disclaimers,
                )
                attempts.append({"attempt": attempt, "audit": audit, "proposal": proposal})
                if audit.get("hard_gate_passed"):
                    sections[latex_key] = (
                        sections[latex_key]
                        + "\\paragraph{Evidence-Bound Narrative Refinement.} "
                        + _narrative_to_latex(audit["text"])
                        + "\n"
                    )
                    break
                feedback = [
                    {"code": item.get("code"), "detail": item.get("detail")}
                    for item in _items(audit.get("failures")) if isinstance(item, dict)
                ]
            except Exception as exc:
                attempts.append({"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
                feedback = [{"code": "NARRATIVE_LLM_CALL_FAILED", "detail": attempts[-1]["error"]}]
        selected = next((item for item in attempts if _mapping(item.get("audit")).get("hard_gate_passed")), None)
        audits[section_id] = {
            "status": "SELECTED" if selected else "DETERMINISTIC_FALLBACK",
            "retry_count": max(0, len(attempts) - 1),
            "attempts": attempts,
        }
    return sections, audits


def render_research_report_sections(
    model: dict[str, Any],
    *,
    use_llm: bool = False,
    llm_callable: Callable[..., dict[str, Any]] | None = None,
    max_narrative_retries: int = MAX_NARRATIVE_RETRIES,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Render deterministic English sections and optionally append audited prose."""
    sections = {
        "metadata": _render_metadata(model),
        "abstract": _render_abstract(model),
        "research_status": _render_research_status(model),
        "problem_and_sh": _render_problem_and_subhypotheses(model),
        "literature_review": _render_literature_review(model),
        "literature_matrix": _render_literature_matrix(model),
        "limitations": _render_limitations(model),
        "per_sh_gaps": _render_gaps(model),
        "combined_gaps": _render_combined_gaps(model),
        "hypotheses": _render_hypotheses(model),
        "iterations": _render_iterations(model),
        "experimental_plan": _render_experiment_plan(model),
        "conclusion": _render_conclusion(model),
    }
    narrative_audit: dict[str, Any] = {"status": "NOT_REQUESTED", "sections": {}}
    if use_llm:
        sections, detailed = _refine_narrative_sections(
            model, sections, llm_callable=llm_callable, max_retries=max_narrative_retries
        )
        narrative_audit = {"status": "COMPLETED", "sections": detailed}
    return sections, narrative_audit


def _bib_escape(value: Any) -> str:
    return _text(value).replace("\\", " ").replace("{", "(").replace("}", ")").replace("%", "\\%")


def render_references_bib(references: list[dict[str, Any]]) -> str:
    entries: list[str] = []
    for reference in references:
        key = _safe_identifier(reference.get("reference_key"), "reference")
        fields = {
            "author": " and ".join(_bib_escape(item) for item in _items(reference.get("authors"))) or "Unknown author",
            "title": _bib_escape(reference.get("title")) or "Untitled record",
            "year": _bib_escape(reference.get("year")) or "n.d.",
            "journal": _bib_escape(reference.get("venue")),
            "doi": _bib_escape(reference.get("doi")),
            "url": _bib_escape(reference.get("url")),
        }
        populated = [f"  {name} = {{{value}}}" for name, value in fields.items() if value]
        entries.append(f"@article{{{key},\n" + ",\n".join(populated) + "\n}\n")
    return "\n".join(entries) or "% No bibliographic records were available.\n"


def _default_template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "Conference-LaTeX-template_10-17-19"


def _main_tex(section_names: list[str] | None = None) -> str:
    """Render the IEEE entry point for either supported report profile.

    Section names originate from the report renderer, not from LLM output, so
    they remain a closed set of paths below ``sections/``.
    """
    inputs = section_names or [
        "metadata", "abstract", "research_status", "problem_and_sh", "literature_review", "literature_matrix", "limitations",
        "per_sh_gaps", "combined_gaps", "hypotheses", "iterations", "experimental_plan", "conclusion",
    ]
    inputs = [_safe_identifier(item, "section") for item in inputs]
    section_inputs = "\n".join(f"\\input{{sections/{item}}}" for item in inputs)
    return (
        "\\documentclass[conference]{IEEEtran}\n"
        "\\IEEEoverridecommandlockouts\n"
        "\\usepackage{cite}\n"
        "\\usepackage{amsmath,amssymb,amsfonts}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage{textcomp}\n"
        "\\usepackage{xcolor}\n"
        "\\begin{document}\n"
        f"{section_inputs}\n"
        "\\bibliographystyle{IEEEtran}\n"
        "\\bibliography{references}\n"
        "\\end{document}\n"
    )


def validate_rendered_report(report_dir: str | Path, model: dict[str, Any], sections: dict[str, str]) -> dict[str, Any]:
    root = Path(report_dir)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    is_full_design = _text(model.get("report_profile")) == "full_research_design"
    expected = [
        root / "main.tex", root / "references.bib", root / "report_manifest.json", root / "claim_evidence_ledger.json",
        root / "project_snapshot.json", root / "report_model.json", root / "narrative_audit.json",
    ]
    if is_full_design:
        expected.extend([
            root / "evidence_cards.json", root / "quantitative_anchor_registry.json", root / "research_argument_graph.json",
            root / "formalization_contracts.json", root / "experiment_design_contracts.json", root / "design_quality_report.json",
        ])
    for path in expected:
        if not path.exists():
            errors.append({"code": "REPORT_ARTIFACT_MISSING", "detail": str(path.name)})
    snapshot_path = root / "project_snapshot.json"
    model_path = root / "report_model.json"
    manifest_path = root / "report_manifest.json"
    if snapshot_path.exists() and model_path.exists() and manifest_path.exists():
        try:
            stored_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            stored_model = json.loads(model_path.read_text(encoding="utf-8"))
            stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _canonical_hash(stored_snapshot) != model.get("project_snapshot_hash"):
                errors.append({"code": "FROZEN_SNAPSHOT_HASH_MISMATCH", "detail": snapshot_path.name})
            if _report_model_hash(stored_model) != model.get("report_model_hash"):
                errors.append({"code": "REPORT_MODEL_HASH_MISMATCH", "detail": model_path.name})
            if stored_manifest.get("project_snapshot_hash") != model.get("project_snapshot_hash"):
                errors.append({"code": "MANIFEST_SNAPSHOT_HASH_MISMATCH", "detail": manifest_path.name})
            if stored_manifest.get("report_model_hash") != model.get("report_model_hash"):
                errors.append({"code": "MANIFEST_MODEL_HASH_MISMATCH", "detail": manifest_path.name})
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            errors.append({"code": "REPORT_AUDIT_ARTIFACT_UNREADABLE", "detail": f"{type(exc).__name__}: {exc}"})
    text = "\n".join(sections.values())
    if _CJK_RE.search(text):
        errors.append({"code": "REPORT_NOT_ENGLISH", "detail": "CJK characters detected in rendered sections"})
    known_keys = {str(item.get("reference_key")) for item in _items(model.get("references")) if isinstance(item, dict)}
    cited_keys = _unique(key for block in _LATEX_CITE_RE.findall(text) for key in block.split(","))
    missing_keys = [key for key in cited_keys if key not in known_keys]
    if missing_keys:
        errors.append({"code": "REPORT_CITATION_KEY_MISSING", "detail": missing_keys})
    if known_keys and not cited_keys:
        warnings.append({"code": "REPORT_HAS_UNCITED_CATALOGUE", "detail": "No literature citation appeared in body text."})
    model_validation = _mapping(model.get("model_validation"))
    if model_validation.get("verdict") != "PASS":
        errors.append({"code": "REPORT_MODEL_AUDIT_FAILED", "detail": model_validation.get("errors", [])})
    if _contains_unsafe_validation_overclaim(text):
        errors.append({"code": "REPORT_OVERCLAIMS_VALIDATION", "detail": "rendered report contains validation overclaim language"})
    if _RESULT_OVERCLAIM_RE.search(text):
        errors.append({"code": "REPORT_TREATS_PREDICTION_AS_RESULT", "detail": "rendered report contains observed-result language"})
    if is_full_design:
        try:
            from ._research_design import validate_full_research_design_render
        except ImportError:  # pragma: no cover - direct-module execution support
            from _research_design import validate_full_research_design_render
        design_validation = validate_full_research_design_render(model, sections)
        errors.extend(_items(design_validation.get("errors")))
        warnings.extend(_items(design_validation.get("warnings")))
    else:
        for section_name in ("problem_and_sh", "per_sh_gaps", "hypotheses"):
            section_text = sections.get(section_name, "")
            if not section_text:
                errors.append({"code": "REPORT_REQUIRED_SECTION_MISSING", "detail": section_name})
        for subhypothesis in _items(model.get("sub_hypotheses")):
            if isinstance(subhypothesis, dict) and _latex_escape(subhypothesis.get("sub_hypothesis_id")) not in text:
                errors.append({"code": "REPORT_SUBHYPOTHESIS_OMITTED", "detail": subhypothesis.get("sub_hypothesis_id")})
        for gap in _items(model.get("gaps")):
            if isinstance(gap, dict) and _latex_escape(gap.get("gap_id")) not in text:
                errors.append({"code": "REPORT_GAP_OMITTED", "detail": gap.get("gap_id")})
        for hypothesis in _items(model.get("hypotheses")):
            if isinstance(hypothesis, dict) and _latex_escape(hypothesis.get("hypothesis_id")) not in text:
                errors.append({"code": "REPORT_HYPOTHESIS_OMITTED", "detail": hypothesis.get("hypothesis_id")})
        for gap in _items(model.get("gaps")):
            if isinstance(gap, dict) and gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE":
                disclaimer = _text(gap.get("disclaimer"))
                if disclaimer and disclaimer not in text:
                    errors.append({"code": "REPORT_RESTRICTED_GAP_DISCLAIMER_OMITTED", "detail": gap.get("gap_id")})
        for hypothesis in _items(model.get("hypotheses")):
            if isinstance(hypothesis, dict) and hypothesis.get("disclaimer"):
                disclaimer = _text(hypothesis.get("disclaimer"))
                if disclaimer not in text:
                    errors.append({"code": "REPORT_HYPOTHESIS_DISCLAIMER_OMITTED", "detail": hypothesis.get("hypothesis_id")})
        for combined in _items(model.get("combined_gaps")):
            if isinstance(combined, dict) and combined.get("status") == "COMBINABLE" and not combined.get("compatibility_gate_passed"):
                errors.append({"code": "REPORT_FORCED_COMBINED_GAP", "detail": combined.get("combined_gap_id")})
    return {
        "verdict": "PASS" if not errors else "REJECT",
        "errors": errors,
        "warnings": warnings,
        "citation_keys": cited_keys,
        "checks": {
            "identifier_chain_audited": True,
            "citation_keys_checked": True,
            "source_unit_provenance_checked": True,
            "all_subhypotheses_rendered": not any(item.get("code") in {"REPORT_SUBHYPOTHESIS_OMITTED", "FULL_REPORT_SUBHYPOTHESIS_OMITTED"} for item in errors),
            "prediction_result_boundary_checked": True,
            "restricted_scope_checked": True,
            "unresolved_fields_retained": _mapping(model_validation.get("coverage")).get("unresolved_fields", []),
        },
    }


def _latex_log_quality_audit(logs: list[dict[str, Any]]) -> dict[str, Any]:
    combined = "\n".join(_text(item.get("tail")) for item in logs)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if re.search(r"(?:Citation .+ undefined|There were undefined references|undefined citations)", combined, flags=re.IGNORECASE):
        errors.append({"code": "PDF_UNRESOLVED_CITATION", "detail": "LaTeX reported an undefined citation or reference."})
    if "??" in combined:
        errors.append({"code": "PDF_UNRESOLVED_REFERENCE_TOKEN", "detail": "LaTeX log contains an unresolved reference token."})
    if re.search(r"Overfull \\[hv]box", combined):
        warnings.append({"code": "PDF_OVERFULL_BOX", "detail": "LaTeX reported a possible table or line overflow."})
    if re.search(r"Underfull \\[hv]box", combined):
        warnings.append({"code": "PDF_UNDERFULL_BOX", "detail": "LaTeX reported loose spacing."})
    if re.search(r"Rerun to get cross-references right", combined):
        errors.append({"code": "PDF_RERUN_REQUIRED", "detail": "Cross-references were not stable after compilation."})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": warnings}


def _latex_source_quality_audit(root: Path) -> dict[str, Any]:
    """Preflight audit for layout risks visible before PDF rasterization."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    main_path = root / "main.tex"
    if not main_path.exists():
        return {"verdict": "REJECT", "errors": [{"code": "LATEX_MAIN_MISSING", "detail": "main.tex"}], "warnings": []}
    main_text = main_path.read_text(encoding="utf-8", errors="replace")
    for name in re.findall(r"\\input\{sections/([^}]+)\}", main_text):
        if not (root / "sections" / f"{name}.tex").exists():
            errors.append({"code": "LATEX_SECTION_INPUT_MISSING", "detail": name})
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in [main_path, *sorted((root / "sections").glob("*.tex"))]
    )
    if source.count("\\begin{") != source.count("\\end{"):
        errors.append({"code": "LATEX_ENVIRONMENT_COUNT_MISMATCH", "detail": "begin/end command counts differ"})
    if "??" in source:
        errors.append({"code": "LATEX_UNRESOLVED_REFERENCE_TOKEN", "detail": "Source contains ??"})
    for match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", source):
        filename = match.group(1)
        if not any((root / f"{filename}{suffix}").exists() for suffix in ("", ".pdf", ".png", ".jpg", ".jpeg")):
            warnings.append({"code": "LATEX_FIGURE_PATH_NOT_RESOLVED_PREFLIGHT", "detail": filename})
    for line in source.splitlines():
        if "\\begin{tabular}" not in line:
            continue
        widths = [float(value) for value in re.findall(r"p\{([0-9.]+)\\textwidth\}", line)]
        if widths and sum(widths) > 0.98:
            warnings.append({"code": "LATEX_TABLE_WIDTH_RISK", "detail": {"fraction_of_textwidth": round(sum(widths), 3)}})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": warnings}


def _resolve_executable(candidate: Any) -> str:
    """Resolve an explicit executable path or a PATH command without guessing."""
    value = _text(candidate)
    if not value:
        return ""
    path = Path(value)
    if path.is_file():
        return str(path)
    return shutil.which(value) or ""


def _bundled_miktex_executable_candidates(template_dir: Path | None, executable: str) -> list[str]:
    """Locate a standard per-user MiKTeX install when the template ships its config.

    The template's ``.miktex-config`` directory is a signal that a portable or
    per-user MiKTeX installation is intended.  It is configuration data, not
    an executable directory, so resolve the normal Windows installation roots
    explicitly rather than assuming that MiKTeX was added to PATH.
    """
    if not template_dir or not (template_dir / ".miktex-config").is_dir() or os.name != "nt":
        return []
    executable_name = executable if executable.lower().endswith(".exe") else f"{executable}.exe"
    roots = _unique([
        os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    ])
    candidates: list[str] = []
    for root in roots:
        base = Path(root)
        candidates.extend([
            str(base / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / executable_name),
            str(base / "MiKTeX" / "miktex" / "bin" / "x64" / executable_name),
            str(base / "MiKTeX" / "bin" / "x64" / executable_name),
        ])
    return candidates


def resolve_tex_toolchain(
    *,
    template_dir: str | Path | None = None,
    latex_engine_path: str = "",
    bibtex_path: str = "",
    pdf_renderer_path: str = "",
) -> dict[str, Any]:
    """Discover a reproducible TeX/PDF toolchain with explicit precedence.

    The caller may pass absolute executables, set environment variables, or
    commit a small ``research_report_toolchain.json`` next to the IEEE template.
    If that template contains ``.miktex-config``, standard Windows per-user
    MiKTeX locations are checked before PATH. The function reports the exact
    choice in the manifest; it never downloads or installs a TeX distribution
    as a side effect.
    """
    configured: dict[str, Any] = {}
    root = Path(template_dir) if template_dir else None
    miktex_config_dir = root / ".miktex-config" if root else None
    if root and root.exists():
        for filename in ("research_report_toolchain.json", ".research_report_toolchain.json"):
            path = root / filename
            if not path.is_file():
                continue
            try:
                configured = _mapping(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                configured = {}
            break
    engine_candidates = [
        latex_engine_path, os.environ.get("SCIENCE_LATEX_ENGINE", ""), configured.get("latex_engine_path", ""),
        configured.get("latex_engine", ""), *_bundled_miktex_executable_candidates(root, "pdflatex"), "pdflatex",
    ]
    bibtex_candidates = [
        bibtex_path, os.environ.get("SCIENCE_BIBTEX", ""), configured.get("bibtex_path", ""), configured.get("bibtex", ""),
        *_bundled_miktex_executable_candidates(root, "bibtex"), "bibtex",
    ]
    renderer_candidates = [
        pdf_renderer_path, os.environ.get("SCIENCE_PDF_RENDERER", ""), configured.get("pdf_renderer_path", ""), configured.get("pdf_renderer", ""), "pdftoppm",
    ]
    engine = next((found for candidate in engine_candidates if (found := _resolve_executable(candidate))), "")
    bibtex = next((found for candidate in bibtex_candidates if (found := _resolve_executable(candidate))), "")
    renderer = next((found for candidate in renderer_candidates if (found := _resolve_executable(candidate))), "")
    return {
        "status": "AVAILABLE" if engine else "LATEX_ENGINE_NOT_FOUND",
        "latex_engine": engine,
        "bibtex": bibtex,
        "pdf_renderer": renderer,
        "template_dir": str(root) if root else "",
        "bundled_miktex_config_dir": str(miktex_config_dir) if miktex_config_dir and miktex_config_dir.is_dir() else "",
        "configured_toolchain": bool(configured),
        "discovery_precedence": ["explicit argument", "environment", "template toolchain file", "bundled MiKTeX config + standard Windows install", "PATH"],
    }


def _pdf_page_count(pdf_path: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        try:
            completed = subprocess.run([pdfinfo, str(pdf_path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            match = re.search(r"^Pages:\s*(\d+)", completed.stdout, flags=re.MULTILINE)
            if completed.returncode == 0 and match:
                return int(match.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        import fitz  # PyMuPDF is a local fallback when Poppler is unavailable.
        with fitz.open(pdf_path) as document:
            return len(document)
    except Exception:
        return None


def _preview_visual_heuristics(pages: list[Path]) -> dict[str, Any]:
    """Detect blank pages and content touching an image edge; this is not human review."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        from PIL import Image, ImageChops
        for path in pages:
            with Image.open(path).convert("RGB") as image:
                white = Image.new("RGB", image.size, "white")
                bbox = ImageChops.difference(image, white).getbbox()
                if bbox is None:
                    errors.append({"code": "PDF_VISUAL_BLANK_PAGE", "detail": path.name})
                    continue
                left, top, right, bottom = bbox
                edge_margin = min(left, top, max(0, image.width - right), max(0, image.height - bottom))
                if edge_margin < 3:
                    warnings.append({"code": "PDF_VISUAL_CONTENT_NEAR_EDGE", "detail": {"page": path.name, "pixels": edge_margin}})
    except Exception as exc:
        warnings.append({"code": "PDF_VISUAL_HEURISTIC_UNAVAILABLE", "detail": f"{type(exc).__name__}: {exc}"})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": warnings,
            "scope": "Automated raster heuristic only; final human visual inspection remains a separate step."}


def _render_pdf_previews(root: Path, pdf_path: Path, *, renderer_path: str = "") -> dict[str, Any]:
    renderer = _resolve_executable(renderer_path) or shutil.which("pdftoppm")
    prefix = root / "pdf_preview"
    for stale in root.glob("pdf_preview-*.png"):
        stale.unlink(missing_ok=True)
    render_method = "pdftoppm"
    render_error = ""
    if renderer:
        try:
            completed = subprocess.run(
                [renderer, "-png", "-r", "150", str(pdf_path), str(prefix)], cwd=root, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if completed.returncode != 0:
                render_error = (completed.stdout + completed.stderr)[-1000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            render_error = f"{type(exc).__name__}: {exc}"
    else:
        render_error = "pdftoppm is not available"
    pages = [Path(path) for path in sorted(root.glob("pdf_preview-*.png"))]
    if not pages:
        render_method = "pymupdf"
        try:
            import fitz
            with fitz.open(pdf_path) as document:
                for page_number, page in enumerate(document, start=1):
                    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(root / f"pdf_preview-{page_number}.png")
            pages = [Path(path) for path in sorted(root.glob("pdf_preview-*.png"))]
        except Exception as exc:
            render_error = f"{render_error}; PyMuPDF fallback: {type(exc).__name__}: {exc}".strip("; ")
    page_count = _pdf_page_count(pdf_path)
    errors: list[dict[str, Any]] = []
    if not pages:
        errors.append({"code": "PDF_PREVIEW_MISSING", "detail": render_error or "No page preview was emitted."})
    if page_count is not None and len(pages) != page_count:
        errors.append({"code": "PDF_PREVIEW_PAGE_COUNT_MISMATCH", "detail": {"pdf": page_count, "rendered": len(pages)}})
    visual = _preview_visual_heuristics(pages) if pages else {"verdict": "NOT_RUN", "errors": [], "warnings": []}
    errors.extend(_items(visual.get("errors")))
    return {
        "status": "RENDERED" if not errors else "PDF_RENDER_FAILED",
        "rendered_pages": [str(path) for path in pages],
        "page_count": page_count,
        "errors": errors,
        "render_method": render_method,
        "visual_heuristics": visual,
        "visual_verification": "AUTOMATED_PREVIEW_CHECK_PASS_HUMAN_INSPECTION_PENDING" if not errors else "FAILED",
    }


def compile_research_report_pdf(
    report_dir: str | Path,
    *,
    template_dir: str | Path | None = None,
    latex_engine_path: str = "",
    bibtex_path: str = "",
    pdf_renderer_path: str = "",
) -> dict[str, Any]:
    """Compile and QA the report with a recorded, configurable local toolchain.

    Compilation is intentionally local-only.  A rendered preview is checked by
    a conservative raster heuristic, then marked as pending human visual
    inspection rather than being misrepresented as a human review.
    """
    root = Path(report_dir)
    toolchain = resolve_tex_toolchain(
        template_dir=template_dir, latex_engine_path=latex_engine_path,
        bibtex_path=bibtex_path, pdf_renderer_path=pdf_renderer_path,
    )
    engine = _text(toolchain.get("latex_engine"))
    if not engine:
        return {
            "status": "SKIPPED_LATEX_ENGINE_NOT_FOUND", "pdf_path": "", "rendered_pages": [],
            "toolchain": toolchain,
            "qa": {"verdict": "NOT_RUN", "reason": "No configured or PATH-discoverable pdflatex engine is available"},
        }
    source_preflight = _latex_source_quality_audit(root)
    if source_preflight.get("verdict") != "PASS":
        return {
            "status": "SKIPPED_LATEX_SOURCE_QA_FAILED", "pdf_path": "", "rendered_pages": [],
            "toolchain": toolchain, "source_preflight": source_preflight,
            "qa": source_preflight,
        }
    bibtex = _text(toolchain.get("bibtex"))
    has_bibliography = (root / "references.bib").exists() and "@" in (root / "references.bib").read_text(encoding="utf-8", errors="replace")
    if has_bibliography and not bibtex:
        return {
            "status": "SKIPPED_BIBTEX_ENGINE_NOT_FOUND", "pdf_path": "", "rendered_pages": [],
            "toolchain": toolchain,
            "qa": {"verdict": "NOT_RUN", "reason": "Bibliography entries require a configured or PATH-discoverable bibtex engine."},
        }
    commands = [[engine, "-interaction=nonstopmode", "-halt-on-error", "main.tex"]]
    if has_bibliography and bibtex:
        commands.extend([
            [bibtex, "main"], [engine, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            [engine, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        ])
    logs: list[dict[str, Any]] = []
    try:
        for command in commands:
            completed = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            logs.append({"command": command, "returncode": completed.returncode, "tail": (completed.stdout + completed.stderr)[-5000:]})
            if completed.returncode != 0:
                qa = _latex_log_quality_audit(logs)
                qa["errors"] = _items(qa.get("errors")) + [{
                    "code": "PDF_LATEX_COMMAND_FAILED",
                    "detail": {"command": command[0], "returncode": completed.returncode},
                }]
                qa["verdict"] = "REJECT"
                return {
                    "status": "LATEX_COMPILE_FAILED", "pdf_path": "", "logs": logs, "rendered_pages": [],
                    "toolchain": toolchain, "source_preflight": source_preflight, "qa": qa,
                }
    except (OSError, subprocess.TimeoutExpired) as exc:
        qa = _latex_log_quality_audit(logs)
        qa["errors"] = _items(qa.get("errors")) + [{"code": "PDF_LATEX_COMMAND_EXCEPTION", "detail": f"{type(exc).__name__}: {exc}"}]
        qa["verdict"] = "REJECT"
        return {
            "status": "LATEX_COMPILE_FAILED", "pdf_path": "", "reason": f"{type(exc).__name__}: {exc}", "logs": logs,
            "rendered_pages": [], "toolchain": toolchain, "source_preflight": source_preflight, "qa": qa,
        }
    pdf_path = root / "main.pdf"
    qa = _latex_log_quality_audit(logs)
    qa["warnings"] = _items(qa.get("warnings")) + _items(source_preflight.get("warnings"))
    preview = _render_pdf_previews(root, pdf_path, renderer_path=_text(toolchain.get("pdf_renderer"))) if pdf_path.exists() else {"status": "PDF_MISSING", "rendered_pages": [], "errors": [{"code": "PDF_MISSING", "detail": "main.pdf was not produced."}]}
    if _items(preview.get("errors")):
        qa["errors"] = _items(qa.get("errors")) + _items(preview.get("errors"))
        qa["verdict"] = "REJECT"
    qa["warnings"] = _items(qa.get("warnings")) + _items(_mapping(preview.get("visual_heuristics")).get("warnings"))
    status = "COMPILED_PENDING_VISUAL_INSPECTION" if pdf_path.exists() and qa.get("verdict") == "PASS" else "COMPILED_WITH_QA_ERRORS"
    return {
        "status": status,
        "pdf_path": str(pdf_path) if pdf_path.exists() else "",
        "logs": logs,
        "rendered_pages": preview.get("rendered_pages", []),
        "preview": preview,
        "toolchain": toolchain,
        "source_preflight": source_preflight,
        "qa": qa,
    }


def write_research_report(
    project: dict[str, Any],
    *,
    report_id: str = "",
    output_dir: str | Path | None = None,
    template_dir: str | Path | None = None,
    use_llm: bool = False,
    llm_callable: Callable[..., dict[str, Any]] | None = None,
    max_narrative_retries: int = MAX_NARRATIVE_RETRIES,
    report_profile: str = "traceability_report",
    max_design_review_rounds: int = 2,
    latex_engine_path: str = "",
    bibtex_path: str = "",
    pdf_renderer_path: str = "",
    compile_pdf: bool = True,
) -> dict[str, Any]:
    """Write a complete report bundle without changing ``project`` or its store."""
    profile = _text(report_profile) or "traceability_report"
    if profile not in {"traceability_report", "full_research_design"}:
        raise ValueError("report_profile must be 'traceability_report' or 'full_research_design'")
    model = build_research_report_model(project, report_id=report_id)
    full_profile = profile == "full_research_design"
    if full_profile:
        try:
            from ._research_design import (
                build_full_research_design_model,
                full_research_design_section_order,
                render_full_research_design_sections,
            )
        except ImportError:  # pragma: no cover - direct-module execution support
            from _research_design import (
                build_full_research_design_model,
                full_research_design_section_order,
                render_full_research_design_sections,
            )
        model = build_full_research_design_model(model)
        counts = _mapping(model.get("source_project_fields"))
        counts.update({
            "evidence_card_count": len(_items(model.get("evidence_cards"))),
            "quantitative_anchor_count": len(_items(model.get("quantitative_anchors"))),
            "argument_graph_node_count": _mapping(model.get("argument_graph")).get("node_count", 0),
            "argument_graph_edge_count": _mapping(model.get("argument_graph")).get("edge_count", 0),
            "formalization_contract_count": len(_items(model.get("formalizations"))),
            "experiment_design_contract_count": len(_items(model.get("experiment_designs"))),
        })
        model["source_project_fields"] = counts
        model.pop("report_model_hash", None)
        model["report_model_hash"] = _report_model_hash(model)
    project_id = _safe_identifier(_mapping(model.get("project")).get("project_id"), "project")
    report_id = _safe_identifier(model.get("report_id"), "report")
    if output_dir is None:
        try:
            from .config import SCIENCE_DIR
        except ImportError:
            from config import SCIENCE_DIR
        destination = Path(SCIENCE_DIR) / "reports" / project_id / report_id
    else:
        destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    section_dir = destination / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    selected_template = Path(template_dir) if template_dir else _default_template_dir()
    if full_profile:
        sections, narrative_audit = render_full_research_design_sections(
            model,
            use_llm=use_llm,
            llm_callable=llm_callable,
            max_narrative_retries=max_narrative_retries,
            max_review_rounds=max_design_review_rounds,
        )
        section_order = full_research_design_section_order(model)
    else:
        sections, narrative_audit = render_research_report_sections(
            model,
            use_llm=use_llm,
            llm_callable=llm_callable,
            max_narrative_retries=max_narrative_retries,
        )
        section_order = list(sections)
    (destination / "main.tex").write_text(_main_tex(section_order), encoding="utf-8")
    for name, body in sections.items():
        (section_dir / f"{name}.tex").write_text(body, encoding="utf-8")
    (destination / "references.bib").write_text(render_references_bib(_items(model.get("references"))), encoding="utf-8")
    if (selected_template / "IEEEtran.cls").exists():
        shutil.copy2(selected_template / "IEEEtran.cls", destination / "IEEEtran.cls")
    if (selected_template / "conference_101719.tex").exists():
        shutil.copy2(selected_template / "conference_101719.tex", destination / "template_reference.tex")
    snapshot_path = destination / "project_snapshot.json"
    model_path = destination / "report_model.json"
    ledger_path = destination / "claim_evidence_ledger.json"
    narrative_audit_path = destination / "narrative_audit.json"
    snapshot_path.write_text(json.dumps(model.get("project_snapshot"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ledger_path.write_text(json.dumps(model.get("claim_evidence_ledger"), ensure_ascii=False, indent=2), encoding="utf-8")
    narrative_audit_path.write_text(json.dumps(narrative_audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    design_artifacts: dict[str, Path] = {}
    if full_profile:
        design_artifacts = {
            "evidence_cards": destination / "evidence_cards.json",
            "quantitative_anchors": destination / "quantitative_anchor_registry.json",
            "argument_graph": destination / "research_argument_graph.json",
            "formalizations": destination / "formalization_contracts.json",
            "experiment_designs": destination / "experiment_design_contracts.json",
            "design_quality": destination / "design_quality_report.json",
        }
        design_artifacts["evidence_cards"].write_text(json.dumps(model.get("evidence_cards"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        design_artifacts["quantitative_anchors"].write_text(json.dumps(model.get("quantitative_anchors"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        design_artifacts["argument_graph"].write_text(json.dumps(model.get("argument_graph"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        design_artifacts["formalizations"].write_text(json.dumps(model.get("formalizations"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        design_artifacts["experiment_designs"].write_text(json.dumps(model.get("experiment_designs"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        design_artifacts["design_quality"].write_text(json.dumps({"quality_rubric": model.get("quality_rubric"), "design_validation": model.get("design_validation")}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    toolchain = resolve_tex_toolchain(
        template_dir=selected_template, latex_engine_path=latex_engine_path,
        bibtex_path=bibtex_path, pdf_renderer_path=pdf_renderer_path,
    )
    manifest = {
        "schema_version": model.get("schema_version", REPORT_SCHEMA_VERSION),
        "report_profile": profile,
        "report_id": report_id,
        "language": REPORT_LANGUAGE,
        "project_id": project_id,
        "project_snapshot_hash": model.get("project_snapshot_hash"),
        "report_model_hash": model.get("report_model_hash"),
        "generated_at": model.get("generated_at"),
        "template_source": str(selected_template),
        "template_exists": selected_template.exists(),
        "model_validation": model.get("model_validation"),
        "narrative_audit": narrative_audit,
        "source_counts": model.get("source_project_fields"),
        "design_validation": model.get("design_validation") if full_profile else None,
        "quality_rubric": model.get("quality_rubric") if full_profile else None,
        "tex_toolchain": toolchain,
        "artifacts": {
            "frozen_snapshot": snapshot_path.name,
            "report_model": model_path.name,
            "claim_evidence_ledger": ledger_path.name,
            "narrative_audit": narrative_audit_path.name,
            "sections": sorted(f"sections/{name}.tex" for name in sections),
        },
        "read_only": True,
    }
    if design_artifacts:
        manifest["artifacts"].update({name: path.name for name, path in design_artifacts.items()})
    (destination / "report_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = validate_rendered_report(destination, model, sections)
    (destination / "validation_report.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    compilation = compile_research_report_pdf(
        destination,
        template_dir=selected_template,
        latex_engine_path=latex_engine_path,
        bibtex_path=bibtex_path,
        pdf_renderer_path=pdf_renderer_path,
    ) if compile_pdf and validation.get("verdict") == "PASS" else {"status": "SKIPPED_VALIDATION_FAILED", "pdf_path": "", "rendered_pages": [], "toolchain": toolchain}
    pdf_verification_path = destination / "pdf_verification_report.json"
    pdf_verification_path.write_text(json.dumps(compilation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    manifest["artifacts"]["validation_report"] = "validation_report.json"
    manifest["artifacts"]["pdf_verification_report"] = pdf_verification_path.name
    manifest["pdf_compilation"] = {
        "status": compilation.get("status"),
        "pdf_path": compilation.get("pdf_path", ""),
        "qa_verdict": _mapping(compilation.get("qa")).get("verdict", "NOT_RUN"),
        "visual_verification": _mapping(compilation.get("preview")).get("visual_verification", "NOT_RUN"),
    }
    (destination / "report_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "REPORT_WRITTEN" if validation.get("verdict") == "PASS" else "REPORT_WRITTEN_WITH_VALIDATION_ERRORS",
        "report_id": report_id,
        "project_id": project_id,
        "output_dir": str(destination),
        "main_tex_path": str(destination / "main.tex"),
        "manifest_path": str(destination / "report_manifest.json"),
        "snapshot_path": str(snapshot_path),
        "report_model_path": str(model_path),
        "ledger_path": str(ledger_path),
        "narrative_audit_path": str(narrative_audit_path),
        "validation_path": str(destination / "validation_report.json"),
        "pdf_verification_path": str(pdf_verification_path),
        "validation": validation,
        "compilation": compilation,
        "report_profile": profile,
        "design_artifacts": {name: str(path) for name, path in design_artifacts.items()},
        "model": model,
    }


def generate_research_report(
    project_id: str,
    *,
    report_id: str = "",
    output_dir: str = "",
    template_dir: str = "",
    use_llm: bool = False,
    max_narrative_retries: int = MAX_NARRATIVE_RETRIES,
    report_profile: str = "traceability_report",
    max_design_review_rounds: int = 2,
    latex_engine_path: str = "",
    bibtex_path: str = "",
    pdf_renderer_path: str = "",
    compile_pdf: bool = True,
) -> str:
    """Public entry point for traceability or full research-design report bundles."""
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    result = write_research_report(
        project,
        report_id=report_id,
        output_dir=output_dir or None,
        template_dir=template_dir or None,
        use_llm=use_llm,
        max_narrative_retries=max_narrative_retries,
        report_profile=report_profile,
        max_design_review_rounds=max_design_review_rounds,
        latex_engine_path=latex_engine_path,
        bibtex_path=bibtex_path,
        pdf_renderer_path=pdf_renderer_path,
        compile_pdf=compile_pdf,
    )
    result.pop("model", None)
    return json.dumps(result, ensure_ascii=False, indent=2)
