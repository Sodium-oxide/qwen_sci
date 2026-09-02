"""Compact, reference-first persistence helpers for V2 source evidence.

The V2 extraction pipeline needs rich source spans while it is running.  A
durable project snapshot does not: a span owns the verbatim quote, the document
record is stored once per paper, and an assertion refers to its span by id.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any
import json
from uuid import NAMESPACE_URL, uuid5


EVIDENCE_STORAGE_SCHEMA_VERSION = "research_question_evidence_storage_v4"
SOURCE_SPAN_SET_SCHEMA_VERSION = "source_span_set_v1"
EVIDENCE_ASSERTION_SET_SCHEMA_VERSION = "evidence_assertion_set_v1"
EVIDENCE_RECORD_REGISTRY_SCHEMA_VERSION = "evidence_record_registry_v1"
EVIDENCE_RECORD_REGISTRY_ROOT_SCHEMA_VERSION = "evidence_record_registry_root_v3"
EVIDENCE_RECORD_REGISTRY_SHARD_SCHEMA_VERSION = "evidence_record_registry_shard_v3"
EVIDENCE_REGISTRY_SHARD_PREFIX_LENGTH = 2
EVIDENCE_STORAGE_V4_SCHEMA_VERSION = EVIDENCE_STORAGE_SCHEMA_VERSION


def _text(value: Any) -> str:
    return str(value or "").strip()


def evidence_registry_shard_key(identifier: Any) -> str:
    """Return the stable content-addressed shard for one evidence id."""

    normalized = _text(identifier)
    if not normalized:
        raise ValueError("Evidence registry shard requires a non-empty identifier")
    return sha256(normalized.encode("utf-8")).hexdigest()[:EVIDENCE_REGISTRY_SHARD_PREFIX_LENGTH]


def _source_document(record: dict[str, Any]) -> dict[str, Any]:
    document = record.get("evidence_document_v2")
    if isinstance(document, dict):
        return deepcopy(document)
    for span in record.get("source_spans_v2", []):
        if isinstance(span, dict) and isinstance(span.get("document"), dict):
            return deepcopy(span["document"])
    return {}


def compact_source_span(span: dict[str, Any]) -> dict[str, Any]:
    """Remove fields duplicated by the paper-level document or quote payload."""

    compacted = deepcopy(span if isinstance(span, dict) else {})
    compacted.pop("document", None)
    quote = _text(compacted.get("quote"))
    if _text(compacted.get("excerpt")) == quote:
        compacted.pop("excerpt", None)
    if _text(compacted.get("excerpt_hash")) == _text(compacted.get("quote_hash")):
        compacted.pop("excerpt_hash", None)
    return compacted


def compact_evidence_assertion(assertion: dict[str, Any]) -> dict[str, Any]:
    """Persist assertion semantics without copying its source span or quote."""

    compacted = deepcopy(assertion if isinstance(assertion, dict) else {})
    source_span = compacted.pop("source_span", None)
    if not _text(compacted.get("paper_id")) and isinstance(source_span, dict):
        compacted["paper_id"] = _text(source_span.get("paper_id"))
    if not _text(compacted.get("document_version_hash")) and isinstance(source_span, dict):
        compacted["document_version_hash"] = _text(source_span.get("document_version_hash"))
    quote = _text(compacted.pop("quote", ""))
    if quote and not _text(compacted.get("quote_hash")):
        # Callers already construct a hash.  Do not synthesize a new one here
        # because this helper deliberately has no hashing policy of its own.
        compacted["quote_hash"] = ""
    compacted.pop("source_quote", None)
    return compacted


def compact_record_v2_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Compact an in-memory PaperGraph record in place and return it.

    This operation is idempotent, so it also upgrades snapshots created before
    reference-first V2 persistence.  It never removes an assertion's span id,
    document version, offsets, or semantic fields.
    """

    if not isinstance(record, dict):
        return record
    document = _source_document(record)
    spans = [
        compact_source_span(item)
        for item in record.get("source_spans_v2", [])
        if isinstance(item, dict)
    ]
    assertions = [
        compact_evidence_assertion(item)
        for item in record.get("evidence_assertions_v2", [])
        if isinstance(item, dict)
    ]
    if document:
        record["evidence_document_v2"] = document
    if "source_spans_v2" in record:
        record["source_spans_v2"] = spans
    if "evidence_assertions_v2" in record:
        record["evidence_assertions_v2"] = assertions
    return record


def compact_record_v3_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Compact only current V3 evidence fields, without adapting V2 records.

    The named V3 fields are an intentional cutover boundary.  If a caller
    hands in historic fields, this function ignores them rather than copying
    or translating them into the current evidence ledger.
    """

    if not isinstance(record, dict):
        return record
    document = record.get("evidence_document_v3")
    if document is not None and (
        not isinstance(document, dict)
        or _text(document.get("schema_version")) != "document_version_v3"
    ):
        raise ValueError("V3 evidence record requires document_version_v3")
    spans = [
        compact_source_span(item)
        for item in record.get("source_spans_v3", [])
        if isinstance(item, dict)
    ]
    if any(_text(item.get("schema_version")) != "source_span_v3" for item in spans):
        raise ValueError("V3 evidence record rejects a non-V3 source span")
    assertions = [
        compact_evidence_assertion(item)
        for item in record.get("evidence_assertions_v3", [])
        if isinstance(item, dict)
    ]
    if any(_text(item.get("schema_version")) != "evidence_assertion_v3" for item in assertions):
        raise ValueError("V3 evidence record rejects a non-V3 assertion")
    if isinstance(document, dict):
        record["evidence_document_v3"] = deepcopy(document)
    if "source_spans_v3" in record:
        record["source_spans_v3"] = spans
    if "evidence_assertions_v3" in record:
        record["evidence_assertions_v3"] = assertions
    return record


def compact_record_v4_evidence(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return record
    document = record.get("evidence_document_v4")
    if document is not None and (
        not isinstance(document, dict)
        or _text(document.get("schema_version")) != "document_version_v4"
    ):
        raise ValueError("V4 evidence record requires document_version_v4")
    spans = [
        compact_source_span(item)
        for item in record.get("source_spans_v6", [])
        if isinstance(item, dict)
    ]
    if any(_text(item.get("schema_version")) != "source_span_v6" for item in spans):
        raise ValueError("Current evidence record rejects a non-V6 source span")
    assertions = [
        compact_evidence_assertion(item)
        for item in record.get("evidence_assertions_v4", [])
        if isinstance(item, dict)
    ]
    if any(_text(item.get("schema_version")) != "evidence_assertion_v4" for item in assertions):
        raise ValueError("V4 evidence record rejects a non-V4 assertion")
    if isinstance(document, dict):
        record["evidence_document_v4"] = deepcopy(document)
    if "source_spans_v6" in record:
        record["source_spans_v6"] = spans
    if "evidence_assertions_v4" in record:
        record["evidence_assertions_v4"] = assertions
    return record


def evidence_contract_partition_v4(record: dict[str, Any]) -> str:
    source = record if isinstance(record, dict) else {}
    assertions = source.get("evidence_assertions_v4")
    if not isinstance(assertions, list):
        raise ValueError("V4 evidence partition requires evidence_assertions_v4")
    document = source.get("evidence_document_v4")
    if not isinstance(document, dict) or _text(document.get("schema_version")) != "document_version_v4":
        raise ValueError("V4 evidence partition requires evidence_document_v4")
    contract_versions = sorted({
        "|".join((
            _text(assertion.get("research_question_contract_id")),
            _text(assertion.get("research_question_contract_revision")),
            _text(assertion.get("research_question_contract_hash")),
        ))
        for assertion in assertions
        if isinstance(assertion, dict)
        and _text(assertion.get("research_question_contract_id"))
    })
    material = "|".join([
        _text(source.get("paper_id")),
        _text(document.get("document_version_hash")),
        *contract_versions,
    ])
    return "rqc4_" + uuid5(NAMESPACE_URL, material).hex[:24]


def evidence_contract_partition_v3(record: dict[str, Any]) -> str:
    """Return a V3 contract-set partition without reading historic evidence."""

    source = record if isinstance(record, dict) else {}
    assertions = source.get("evidence_assertions_v3")
    if not isinstance(assertions, list):
        raise ValueError("V3 evidence partition requires evidence_assertions_v3")
    document = source.get("evidence_document_v3")
    if not isinstance(document, dict) or _text(document.get("schema_version")) != "document_version_v3":
        raise ValueError("V3 evidence partition requires evidence_document_v3")
    contract_versions = sorted({
        "|".join((
            _text(assertion.get("research_question_contract_id")),
            _text(assertion.get("research_question_contract_revision")),
            _text(assertion.get("research_question_contract_hash")),
        ))
        for assertion in assertions
        if isinstance(assertion, dict)
        and _text(assertion.get("research_question_contract_id"))
    })
    material = "|".join([
        _text(source.get("paper_id")),
        _text(document.get("document_version_hash")),
        *contract_versions,
    ])
    return "rqc_" + sha256(material.encode("utf-8")).hexdigest()[:24]


def assertion_source_span_ids(assertions: list[dict[str, Any]] | Any) -> list[str]:
    """Return the unique source ids actually used by persisted assertions."""

    result: list[str] = []
    seen: set[str] = set()
    for assertion in assertions if isinstance(assertions, list) else []:
        if not isinstance(assertion, dict):
            continue
        for span_id in assertion.get("source_span_ids", []):
            normalized = _text(span_id)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
    return result


def source_span_by_id(
    source_spans: list[dict[str, Any]] | Any,
) -> dict[str, dict[str, Any]]:
    return {
        _text(item.get("source_span_id") or item.get("source_unit_id")): item
        for item in (source_spans if isinstance(source_spans, list) else [])
        if isinstance(item, dict)
        and _text(item.get("source_span_id") or item.get("source_unit_id"))
    }


def evidence_contract_partition(record: dict[str, Any]) -> str:
    """Return one stable contract-set key for a paper's shared source spans."""

    contract_versions = sorted({
        "|".join((
            _text(assertion.get("research_question_contract_id")),
            _text(assertion.get("research_question_contract_revision")),
            _text(assertion.get("research_question_contract_hash")),
        ))
        for assertion in record.get("evidence_assertions_v2", [])
        if isinstance(assertion, dict)
        and _text(assertion.get("research_question_contract_id"))
    })
    material = "|".join([
        _text(record.get("paper_id")),
        _text((record.get("evidence_document_v2") or {}).get("document_version_hash")),
        *contract_versions,
    ])
    return "rqc_" + sha256(material.encode("utf-8")).hexdigest()[:24]


def encode_indexed_evidence_jsonl(
    records: list[dict[str, Any]],
    *,
    identifier_field: str,
) -> tuple[bytes, dict[str, dict[str, int]]]:
    """Encode immutable evidence records with an offset index keyed by id."""

    chunks: list[bytes] = []
    index: dict[str, dict[str, int]] = {}
    offset = 0
    for record in records:
        identifier = _text(record.get(identifier_field))
        if not identifier or identifier in index:
            continue
        body = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        chunks.append(body + b"\n")
        index[identifier] = {"offset": offset, "length": len(body)}
        offset += len(body) + 1
    return b"".join(chunks), index


def indexed_evidence_document(
    *,
    record_kind: str,
    paper_id: str,
    partition: str,
    jsonl_path: str,
    identifier_field: str,
    entries: dict[str, dict[str, int]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "indexed_research_question_evidence_v1",
        "record_kind": _text(record_kind),
        "paper_id": _text(paper_id),
        "partition": _text(partition),
        "jsonl_path": _text(jsonl_path),
        "identifier_field": _text(identifier_field),
        "entries": deepcopy(entries),
    }
    payload["content_hash"] = "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return payload


def evidence_registry_document(
    *,
    record_kind: str,
    entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": EVIDENCE_RECORD_REGISTRY_SCHEMA_VERSION,
        "record_kind": _text(record_kind),
        "entries": deepcopy(entries),
    }
    payload["content_hash"] = "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return payload


def evidence_registry_shard_document(
    *,
    record_kind: str,
    shard_key: str,
    entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Create one small random-access registry shard.

    Registry roots deliberately reference shards rather than embedding their
    entries.  A normal evidence import therefore rewrites only the affected
    shard, not a project-wide index of every source span or assertion.
    """

    normalized_shard = _text(shard_key).lower()
    if len(normalized_shard) != EVIDENCE_REGISTRY_SHARD_PREFIX_LENGTH:
        raise ValueError("Invalid evidence registry shard key")
    payload = {
        "schema_version": EVIDENCE_RECORD_REGISTRY_SHARD_SCHEMA_VERSION,
        "record_kind": _text(record_kind),
        "shard_key": normalized_shard,
        "entries": deepcopy(entries),
    }
    payload["content_hash"] = "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return payload


def evidence_registry_root_document(
    *,
    record_kind: str,
    shards: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Create the compact root document for a sharded evidence registry."""

    normalized_shards = {
        _text(shard_key).lower(): deepcopy(ref)
        for shard_key, ref in shards.items()
        if _text(shard_key) and isinstance(ref, dict)
    }
    payload = {
        "schema_version": EVIDENCE_RECORD_REGISTRY_ROOT_SCHEMA_VERSION,
        "record_kind": _text(record_kind),
        "shard_key_policy": f"sha256_prefix_{EVIDENCE_REGISTRY_SHARD_PREFIX_LENGTH}",
        "shards": normalized_shards,
    }
    payload["content_hash"] = "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return payload
