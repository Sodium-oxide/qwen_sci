"""Lossless JSON storage for Survey retrieval papers and repeated evidence.

Runtime consumers continue to use full paper objects. Persisted artifacts keep
one record table per object type and ordered ID lists instead of copied objects.
The execution schema is unchanged; ``storage_schema_version`` versions this
separate, reversible representation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from .paper_identity import canonical_paper_id


STORAGE_SCHEMA_VERSION = "subhypothesis_retrieval_refs_v1"
_TABLE_KEYS = ("paper_records", "semantic_assessment_records", "evidence_records")
_PAPER_LISTS = {
    "candidate_papers": "candidate_paper_ids",
    "scientific_candidate_papers": "scientific_candidate_paper_ids",
}
_SELECTION_LISTS = {
    "selected_papers": "selected_paper_ids",
    "evidence_seed_papers": "evidence_seed_paper_ids",
    "exploration_seed_papers": "exploration_seed_paper_ids",
    "context_seed_papers": "context_seed_paper_ids",
    "holdout_candidates": "holdout_candidate_ids",
    "rejected_papers": "rejected_paper_ids",
}
_EVIDENCE_LISTS = {
    "evidence_spans": "evidence_span_ids",
    "llm_evidence_spans": "llm_evidence_span_ids",
    "claim_limits": "claim_limit_ids",
    "llm_claim_limits": "llm_claim_limit_ids",
}


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def serialize_subhypothesis_retrieval(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Build a storage projection without mutating papers, selections, or audits.

    Different snapshots of the same paper ID receive separate record keys. This
    preserves legacy retrieval runs whose discovery and assessed records differ.
    Original model responses and candidate ledgers are retained verbatim.
    """

    if artifact.get("storage_schema_version") is not None:
        expand_subhypothesis_retrieval(artifact)  # Reject invalid stored references.
        return dict(artifact)
    selection = artifact.get("seed_selection")
    selection = selection if isinstance(selection, Mapping) else {}
    if not any(_is_sequence(artifact.get(key)) for key in _PAPER_LISTS) and not any(
        _is_sequence(selection.get(key)) for key in _SELECTION_LISTS
    ):
        return dict(artifact)
    if any(key in artifact for key in _TABLE_KEYS):
        raise ValueError("Retrieval artifact already contains unversioned storage tables")

    papers: dict[str, Any] = {}
    semantics: dict[str, Any] = {}
    evidence: dict[str, Any] = {}

    def intern(table, value, prefix, preferred=""):
        digest = hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        identifier = preferred or f"{prefix}:{digest}"
        if identifier in table and table[identifier] != value:
            identifier = f"{identifier}@{digest}"
        if identifier in table and table[identifier] != value:
            raise ValueError(f"Conflicting retrieval storage record: {identifier}")
        table.setdefault(identifier, value)
        return identifier

    def encode_value(value):
        if isinstance(value, Mapping):
            result = {}
            for key, child in value.items():
                target = key
                if key == "sh_semantic_assessments" and _is_sequence(child):
                    target = "sh_semantic_assessment_ids"
                    child = [intern(semantics, encode_value(item), "assessment") for item in child]
                elif key == "semantic_assessment" and isinstance(child, Mapping):
                    target = "semantic_assessment_id"
                    child = intern(semantics, encode_value(child), "assessment")
                elif key in _EVIDENCE_LISTS and _is_sequence(child):
                    target = _EVIDENCE_LISTS[key]
                    child = [intern(evidence, item, "evidence") for item in child]
                else:
                    child = encode_value(child)
                if target != key and target in value:
                    raise ValueError(f"Retrieval storage field collision: {target}")
                result[target] = child
            return result
        if _is_sequence(value):
            return [encode_value(item) for item in value]
        return value

    def paper_ids(records):
        identifiers = []
        for paper in records:
            if not isinstance(paper, Mapping):
                raise ValueError("Retrieval paper collections must contain paper objects")
            preferred = next((canonical_paper_id(paper.get(key)) for key in (
                "paperId", "paper_id", "openalex_id", "id", "doi",
            ) if paper.get(key)), "")
            identifiers.append(intern(papers, encode_value(paper), "paper", preferred))
        return identifiers

    def encode_lists(value, fields):
        result = {}
        for key, child in value.items():
            if key in fields and _is_sequence(child):
                target = fields[key]
                if target in value:
                    raise ValueError(f"Retrieval storage field collision: {target}")
                result[target] = paper_ids(child)
            elif key == "seed_selection" and isinstance(child, Mapping):
                result[key] = encode_lists(child, _SELECTION_LISTS)
            else:
                result[key] = child
        return result

    result = encode_lists(artifact, _PAPER_LISTS)
    result.update(storage_schema_version=STORAGE_SCHEMA_VERSION,
                  paper_records=papers, semantic_assessment_records=semantics,
                  evidence_records=evidence)
    return result


def expand_subhypothesis_retrieval(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Restore the runtime object shape from either old or referenced storage.

    Unknown storage versions and missing references fail explicitly. Cached
    records restore shared objects instead of copying every selection again.
    """

    version = artifact.get("storage_schema_version")
    if version is None:
        return dict(artifact)
    if version != STORAGE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported retrieval storage schema: {version}")
    for key in _TABLE_KEYS:
        if not isinstance(artifact.get(key), Mapping):
            raise ValueError(f"Retrieval storage requires a {key} table")
    reverse_evidence = {value: key for key, value in _EVIDENCE_LISTS.items()}
    caches: dict[str, dict[str, Any]] = {key: {} for key in _TABLE_KEYS}
    resolving: set[tuple[str, str]] = set()

    def resolve(table_key, identifier):
        table = artifact[table_key]
        if not isinstance(identifier, str) or identifier not in table:
            raise ValueError(f"Missing retrieval storage reference in {table_key}: {identifier!r}")
        cache = caches[table_key]
        if identifier not in cache:
            token = (table_key, identifier)
            if token in resolving:
                raise ValueError(f"Cyclic retrieval storage reference: {identifier}")
            resolving.add(token)
            raw = table[identifier]
            cache[identifier] = deepcopy(raw) if table_key == "evidence_records" else decode_value(raw)
            resolving.remove(token)
        return cache[identifier]

    def resolve_list(table_key, identifiers):
        if not _is_sequence(identifiers):
            raise ValueError(f"Retrieval references to {table_key} must be an ID list")
        return [resolve(table_key, identifier) for identifier in identifiers]

    def decode_value(value):
        if isinstance(value, Mapping):
            result = {}
            for key, child in value.items():
                target = key
                if key == "sh_semantic_assessment_ids":
                    target = "sh_semantic_assessments"
                    child = resolve_list("semantic_assessment_records", child)
                elif key == "semantic_assessment_id":
                    target = "semantic_assessment"
                    child = resolve("semantic_assessment_records", child)
                elif key in reverse_evidence:
                    target = reverse_evidence[key]
                    child = resolve_list("evidence_records", child)
                else:
                    child = decode_value(child)
                if target != key and target in value:
                    raise ValueError(f"Retrieval storage field collision: {target}")
                result[target] = child
            return result
        if _is_sequence(value):
            return [decode_value(item) for item in value]
        return value

    def decode_lists(value, fields):
        reverse = {stored: original for original, stored in fields.items()}
        result = {}
        for key, child in value.items():
            if key in reverse:
                target = reverse[key]
                if target in value:
                    raise ValueError(f"Retrieval storage field collision: {target}")
                result[target] = resolve_list("paper_records", child)
            elif key == "seed_selection" and isinstance(child, Mapping):
                result[key] = decode_lists(child, _SELECTION_LISTS)
            else:
                result[key] = child
        return result

    return decode_lists({key: value for key, value in artifact.items()
                         if key not in (*_TABLE_KEYS, "storage_schema_version")}, _PAPER_LISTS)


def load_subhypothesis_retrieval(path: str | Path) -> dict[str, Any]:
    """Read a standalone retrieval artifact, resolving its storage references."""

    with Path(path).open(encoding="utf-8") as handle:
        return expand_subhypothesis_retrieval(json.load(handle))
