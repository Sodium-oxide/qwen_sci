"""Normalized, reference-only science artifacts.

This module is deliberately storage-agnostic.  It converts the current
monolithic project objects into deterministic gap, evidence-bundle, Socrates
contract/report, and canonical-fragment artifacts without activating the new
store.  ScienceStateManager owns physical paths and transactions; callers must
not write these artifacts by hand.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable
import copy
import json
import re
import unicodedata


SCIENCE_GAP_LEGACY_SCHEMA_VERSION = "science_gap_v1"
SCIENCE_GAP_SCHEMA_VERSION = "science_gap_v2"
MECHANISM_EVIDENCE_BUNDLE_SCHEMA_VERSION = "mechanism_evidence_bundle_v4"
SOCRATES_CONTRACT_SCHEMA_VERSION = "socrates_contract_v2"
SOCRATES_REPORT_SCHEMA_VERSION = "socrates_report_v2"
CANONICAL_FRAGMENT_SCHEMA_VERSION = "canonical_fragment_v1"
NORMALIZED_GAP_ARTIFACT_SET_SCHEMA_VERSION = "normalized_gap_artifact_set_v1"

MAX_FRAGMENT_REFS_PER_SLOT = 3

_TRIADIC = "ALIGNED_TRIADIC_EVIDENCE"
_PARTIAL = "ALIGNED_PARTIAL_EVIDENCE"
_REJECTED_VERDICTS = {"OUT_OF_SCOPE", "BACKGROUND_RATIONALE"}

_GAP_V1_ALLOWED_KEYS = {
    "schema_version", "project_id", "gap_id", "gap_version", "sub_hypothesis_id",
    "description", "gap_type", "source_clue_role", "research_mode",
    "input", "mediator", "outcome", "comparison", "falsification",
    "input_fragment_refs", "mediator_fragment_refs", "outcome_fragment_refs",
    "competing_fragment_refs", "rejected_audit_fragment_refs",
    "evidence_bundle_ref", "latest_contract_ref", "source_snapshot_hash", "content_hash",
}
_GAP_ALLOWED_KEYS = {
    *_GAP_V1_ALLOWED_KEYS,
    "candidate_identity", "claim_level", "claim_statement",
    "claim_verification_verdict", "claim_last_verified_at",
    "claim_requires_external_verification", "claim_scope_kind",
    "source_text_handoff_refs", "evidence_lineage_refs", "source_lineage_status",
    "assertion_ids", "slot_support_ids",
}
_BUNDLE_ALLOWED_KEYS = {
    "schema_version", "project_id", "gap_id", "bundle_version", "status",
    "missing_requirements", "input", "mediator", "outcome",
    "theory_evidence_refs", "experimental_evidence_refs",
    "computational_evidence_refs", "competing_fragment_refs",
    "rejected_audit_fragment_refs", "research_design_evidence",
    "source_text_handoff_refs", "accepted_source_text_handoff_refs",
    "rejected_source_text_handoff_refs", "slot_source_lineage",
    "causal_field_provenance", "mechanism_source_span_refs",
    "accepted_source_lineage", "rejected_source_lineage",
    "evidence_lineage_refs", "source_lineage_status", "content_hash",
}
_CONTRACT_ALLOWED_KEYS = {
    "schema_version", "project_id", "gap_id", "contract_version", "gap_ref",
    "gap_snapshot_hash", "evidence_bundle_ref", "evidence_bundle_hash",
    "contract_status", "missing_requirements", "created_at_state_version", "content_hash",
}
_REPORT_ALLOWED_KEYS = {
    "schema_version", "project_id", "run_id", "gap_id", "contract_ref", "verdict",
    "search_count", "import_count", "missing_requirements", "query_audit_ref", "content_hash",
}
_FRAGMENT_ALLOWED_KEYS = {
    "schema_version", "fragment_id", "paper_id", "alignment_contract_hash",
    "source_field", "sentence_start", "sentence_end", "excerpt", "excerpt_hash",
    "semantic_verdict", "source_role", "supported_roles", "evidence_category",
    "score", "legacy_source_unit_id", "content_hash",
}

_FORBIDDEN_EMBEDDED_KEYS = {
    "mechanism_evidence_bundle",
    "evidence_fragment_alignments",
    "gap_anchor_fragment_alignments",
    "fragment_alignments",
    "mechanism_contract",
    "socrates_reports",
    "socrates_mechanism_contracts",
}


class ScienceArtifactValidationError(ValueError):
    pass


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalized_excerpt(value: Any) -> str:
    return _compact_text(unicodedata.normalize("NFKC", str(value or "")))


def _json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def artifact_content_hash(artifact: dict[str, Any]) -> str:
    payload = {key: value for key, value in artifact.items() if key != "content_hash"}
    return _json_hash(payload)


def _with_content_hash(artifact: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(artifact)
    result["content_hash"] = artifact_content_hash(result)
    return result


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _supported_roles(fragment: dict[str, Any]) -> list[str]:
    explicit = fragment.get("supported_roles") or fragment.get("causal_fields_supported")
    if isinstance(explicit, list):
        values = [str(item) for item in explicit if str(item) in {"input", "mediator", "outcome"}]
        if values:
            return list(dict.fromkeys(values))
    roles: list[str] = []
    for role, key in (
        ("input", "object_alignment"),
        ("mediator", "process_alignment"),
        ("outcome", "outcome_alignment"),
    ):
        assessment = fragment.get(key) if isinstance(fragment.get(key), dict) else {}
        if assessment.get("passes") is True:
            roles.append(role)
    return roles


def _evidence_category(fragment: dict[str, Any]) -> str:
    source_role = str(fragment.get("source_role") or "").lower()
    verdict = str(fragment.get("semantic_verdict") or "").upper()
    evidence_role = str(fragment.get("evidence_role") or "").upper()
    if "COMPETING" in evidence_role or source_role in {"competing", "competing_mechanism"}:
        return "competing"
    if verdict in _REJECTED_VERDICTS or source_role in {"rationale_only", "out_of_scope", "rejected"}:
        return "rejected"
    return "primary"


def _fragment_score(fragment: dict[str, Any], roles: list[str]) -> float:
    verdict = str(fragment.get("semantic_verdict") or "").upper()
    source_role = str(fragment.get("source_role") or "").lower()
    source_alignment = 1.0 if verdict == _TRIADIC else 0.67 if verdict == _PARTIAL else 0.2
    role_specificity = min(1.0, len(set(roles)) / 3.0)
    predicate = fragment.get("gap_predicate_strength")
    try:
        gap_predicate_strength = max(0.0, min(1.0, float(predicate)))
    except (TypeError, ValueError):
        gap_predicate_strength = 0.8 if source_role == "direct" else 0.5 if source_role == "partial" else 0.2
    quality = fragment.get("source_quality_score", fragment.get("publication_quality_score", 0.5))
    try:
        source_quality = max(0.0, min(1.0, float(quality)))
    except (TypeError, ValueError):
        source_quality = 0.5
    start = _as_int(fragment.get("sentence_start"))
    end = _as_int(fragment.get("sentence_end"))
    width = max(1, (end - start + 1) if start is not None and end is not None else 1)
    window_minimality = 1.0 / float(width)
    return round(
        0.35 * source_alignment
        + 0.25 * role_specificity
        + 0.20 * gap_predicate_strength
        + 0.10 * source_quality
        + 0.10 * window_minimality,
        6,
    )


def canonical_fragment(fragment: dict[str, Any], *, alignment_contract_hash: str = "") -> dict[str, Any]:
    """Return one stable, non-recursive canonical fragment artifact."""
    if not isinstance(fragment, dict):
        raise ScienceArtifactValidationError("Canonical fragment input must be an object")
    paper_id = _compact_text(fragment.get("paper_id"))
    excerpt = _normalized_excerpt(fragment.get("excerpt"))
    contract_hash = _compact_text(
        alignment_contract_hash or fragment.get("alignment_contract_hash")
    )
    source_field = _compact_text(fragment.get("source_field") or "unknown")
    if not paper_id:
        raise ScienceArtifactValidationError("Canonical fragment requires paper_id")
    if not contract_hash:
        raise ScienceArtifactValidationError("Canonical fragment requires alignment_contract_hash")
    if not excerpt:
        raise ScienceArtifactValidationError("Canonical fragment requires excerpt")
    sentence_start = _as_int(fragment.get("sentence_start"))
    sentence_end = _as_int(fragment.get("sentence_end"))
    if sentence_start is not None and sentence_end is not None and sentence_end < sentence_start:
        raise ScienceArtifactValidationError("Canonical fragment sentence range is reversed")
    excerpt_digest = sha256(excerpt.encode("utf-8")).hexdigest()
    identity = "\0".join((
        paper_id,
        contract_hash,
        source_field,
        "" if sentence_start is None else str(sentence_start),
        "" if sentence_end is None else str(sentence_end),
        excerpt,
    ))
    roles = _supported_roles(fragment)
    artifact = {
        "schema_version": CANONICAL_FRAGMENT_SCHEMA_VERSION,
        "fragment_id": "frag_" + sha256(identity.encode("utf-8")).hexdigest()[:32],
        "paper_id": paper_id,
        "alignment_contract_hash": contract_hash,
        "source_field": source_field,
        "sentence_start": sentence_start,
        "sentence_end": sentence_end,
        "excerpt": excerpt,
        "excerpt_hash": "sha256:" + excerpt_digest,
        "semantic_verdict": _compact_text(fragment.get("semantic_verdict") or "UNCLASSIFIED"),
        "source_role": _compact_text(fragment.get("source_role") or "unclassified"),
        "supported_roles": roles,
        "evidence_category": _evidence_category(fragment),
        "score": _fragment_score(fragment, roles),
        "legacy_source_unit_id": _compact_text(fragment.get("source_unit_id")),
    }
    result = _with_content_hash(artifact)
    validate_normalized_artifact(result)
    return result


def _information_features(fragment: dict[str, Any]) -> set[str]:
    features = {f"role:{role}" for role in fragment.get("supported_roles", [])}
    excerpt = str(fragment.get("excerpt") or "").lower()
    for token in re.findall(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?:\s*[%a-zA-Zμµ°/^-]+)?", excerpt):
        features.add("quant:" + _compact_text(token))
    if re.search(r"\b(?:uncertain|uncertainty|variance|confidence|error|bias|precision)\b", excerpt):
        features.add("uncertainty")
    if re.search(r"\b(?:boundary|regime|condition|limit|threshold|range|phase)\b", excerpt):
        features.add("boundary_or_regime")
    if re.search(r"\b(?:increase|decrease|positive|negative|opposite|inverse|higher|lower)\b", excerpt):
        features.add("polarity")
    return features


def _window_width(fragment: dict[str, Any]) -> int:
    start = _as_int(fragment.get("sentence_start"))
    end = _as_int(fragment.get("sentence_end"))
    if start is None or end is None:
        return max(1, len(str(fragment.get("excerpt") or "")))
    return max(1, end - start + 1)


def _overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    if any(
        left.get(key) != right.get(key)
        for key in ("paper_id", "alignment_contract_hash", "source_field")
    ):
        return 0.0
    left_start, left_end = _as_int(left.get("sentence_start")), _as_int(left.get("sentence_end"))
    right_start, right_end = _as_int(right.get("sentence_start")), _as_int(right.get("sentence_end"))
    if None in {left_start, left_end, right_start, right_end}:
        return 1.0 if left.get("excerpt_hash") == right.get("excerpt_hash") else 0.0
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start) + 1)
    if overlap == 0:
        return 0.0
    return overlap / float(min(left_end - left_start + 1, right_end - right_start + 1))


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("evidence_category") != right.get("evidence_category"):
        return False
    verdict_rank = {_TRIADIC: 3, _PARTIAL: 2, "BACKGROUND_RATIONALE": 1, "OUT_OF_SCOPE": 0}
    source_role_rank = {"direct": 3, "partial": 2, "rationale_only": 1, "out_of_scope": 0}
    if verdict_rank.get(str(left.get("semantic_verdict") or ""), 0) < verdict_rank.get(str(right.get("semantic_verdict") or ""), 0):
        return False
    if source_role_rank.get(str(left.get("source_role") or ""), 0) < source_role_rank.get(str(right.get("source_role") or ""), 0):
        return False
    left_roles = set(left.get("supported_roles") or [])
    right_roles = set(right.get("supported_roles") or [])
    left_features = _information_features(left)
    right_features = _information_features(right)
    if not left_roles.issuperset(right_roles) or not left_features.issuperset(right_features):
        return False
    adds_information = (
        left_roles > right_roles
        or left_features > right_features
        or verdict_rank.get(str(left.get("semantic_verdict") or ""), 0) > verdict_rank.get(str(right.get("semantic_verdict") or ""), 0)
        or source_role_rank.get(str(left.get("source_role") or ""), 0) > source_role_rank.get(str(right.get("source_role") or ""), 0)
    )
    if adds_information:
        return True
    left_width, right_width = _window_width(left), _window_width(right)
    if left_width != right_width:
        return left_width < right_width
    return (
        float(left.get("score") or 0.0),
        -len(str(left.get("excerpt") or "")),
        str(left.get("fragment_id") or ""),
    ) > (
        float(right.get("score") or 0.0),
        -len(str(right.get("excerpt") or "")),
        str(right.get("fragment_id") or ""),
    )


def deduplicate_and_prune_fragments(
    fragments: Iterable[dict[str, Any]],
    *,
    overlap_threshold: float = 0.5,
) -> dict[str, Any]:
    """Canonicalize, exactly deduplicate, then prune dominated windows."""
    canonical_by_id: dict[str, dict[str, Any]] = {}
    exact_duplicates = 0
    exact_duplicate_audit: list[dict[str, Any]] = []
    for raw in fragments:
        canonical = (
            raw
            if isinstance(raw, dict) and raw.get("schema_version") == CANONICAL_FRAGMENT_SCHEMA_VERSION
            else canonical_fragment(raw)
        )
        validate_normalized_artifact(canonical)
        fragment_id = str(canonical.get("fragment_id") or "")
        if fragment_id in canonical_by_id:
            exact_duplicates += 1
            exact_duplicate_audit.append({
                "decision": "EXACT_DUPLICATE",
                "fragment_ref": fragment_id,
                "legacy_source_unit_id": str(canonical.get("legacy_source_unit_id") or ""),
            })
            if float(canonical.get("score") or 0.0) > float(canonical_by_id[fragment_id].get("score") or 0.0):
                canonical_by_id[fragment_id] = canonical
            continue
        canonical_by_id[fragment_id] = canonical

    candidates = list(canonical_by_id.values())
    adjacency: dict[str, set[str]] = {str(item["fragment_id"]): set() for item in candidates}
    threshold = max(0.0, min(1.0, float(overlap_threshold)))
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            if _overlap_ratio(left, right) >= threshold:
                left_id, right_id = str(left["fragment_id"]), str(right["fragment_id"])
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)

    clusters: list[list[dict[str, Any]]] = []
    by_id = {str(item["fragment_id"]): item for item in candidates}
    unseen = set(by_id)
    while unseen:
        seed = unseen.pop()
        stack = [seed]
        ids = [seed]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
                    ids.append(neighbor)
        clusters.append([by_id[item] for item in ids])

    selected: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = list(exact_duplicate_audit)
    dominated_count = 0
    for cluster_index, cluster in enumerate(clusters, start=1):
        ordered = sorted(
            cluster,
            key=lambda item: (
                -len(set(item.get("supported_roles") or [])),
                -len(_information_features(item)),
                -float(item.get("score") or 0.0),
                _window_width(item),
                str(item.get("fragment_id") or ""),
            ),
        )
        retained: list[dict[str, Any]] = []
        for candidate in ordered:
            dominator = next((item for item in retained if _dominates(item, candidate)), None)
            if dominator is not None:
                dominated_count += 1
                audit.append({
                    "decision": "DOMINATED_WINDOW",
                    "cluster": cluster_index,
                    "dominated_by_fragment_ref": dominator["fragment_id"],
                    "candidate_fragment": candidate,
                })
                continue
            replaced = [item for item in retained if _dominates(candidate, item)]
            for item in replaced:
                retained.remove(item)
                dominated_count += 1
                audit.append({
                    "decision": "DOMINATED_WINDOW",
                    "cluster": cluster_index,
                    "dominated_by_fragment_ref": candidate["fragment_id"],
                    "candidate_fragment": item,
                })
            retained.append(candidate)
        for item in retained:
            selected.append(item)
            audit.append({
                "decision": "RETAINED_CANONICAL_FRAGMENT",
                "cluster": cluster_index,
                "fragment_ref": item["fragment_id"],
            })

    selected.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("fragment_id") or "")))
    return {
        "selected_fragments": selected,
        "audit_records": audit,
        "statistics": {
            "input_count": len(list(fragments)) if isinstance(fragments, list) else len(candidates) + exact_duplicates,
            "unique_exact_count": len(candidates),
            "exact_duplicate_count": exact_duplicates,
            "overlap_cluster_count": len(clusters),
            "dominated_window_count": dominated_count,
            "selected_count": len(selected),
        },
    }


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    return list(dict.fromkeys(_compact_text(item) for item in values if _compact_text(item)))


def _source_text_handoff_ref(item: Any) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    acceptance_status = _compact_text(source.get("acceptance_status"))
    return {
        "source_text_handoff_id": _compact_text(source.get("source_text_handoff_id")),
        "paper_id": _compact_text(source.get("paper_id")),
        "source_unit_id": _compact_text(source.get("source_unit_id")),
        "source_span_id": _compact_text(source.get("source_span_id") or source.get("source_unit_id")),
        "assertion_id": _compact_text(source.get("assertion_id")),
        "slot_support_id": _compact_text(source.get("slot_support_id")),
        "proposition_id": _compact_text(source.get("proposition_id")),
        "section_id": _compact_text(source.get("section_id")),
        "section_type": _compact_text(source.get("section_type")),
        "document_version_hash": _compact_text(source.get("document_version_hash")),
        "quote_char_start": source.get("quote_char_start"),
        "quote_char_end": source.get("quote_char_end"),
        "document_char_start": source.get("document_char_start"),
        "document_char_end": source.get("document_char_end"),
        "exact_quote": _compact_text(source.get("exact_quote") or source.get("excerpt")),
        "excerpt_hash": _compact_text(source.get("excerpt_hash")),
        "source_field": _compact_text(source.get("source_field")),
        "source_origin": _compact_text(source.get("source_origin")),
        "source_role": _compact_text(source.get("source_role")),
        "binding_status": _compact_text(source.get("binding_status")),
        "acceptance_status": acceptance_status,
        "package_slot": _compact_text(source.get("package_slot")),
        "slot": _compact_text(source.get("slot") or source.get("package_slot")),
        "causal_field": _compact_text(source.get("causal_field") or source.get("accepted_causal_field")),
        "supported_value": _compact_text(source.get("supported_value") or source.get("value")),
        "accepted": acceptance_status == "ACCEPTED_FOR_PACKAGE_SLOT",
        "rejection_reason": _compact_text(source.get("rejection_reason")),
    }


def _source_text_handoff_refs(values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        ref = _source_text_handoff_ref(item)
        key = (
            str(ref.get("source_text_handoff_id") or ""),
            str(ref.get("source_unit_id") or ""),
            str(ref.get("package_slot") or ""),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs


def _slot_source_lineage_refs(value: Any) -> dict[str, list[dict[str, Any]]]:
    source = value if isinstance(value, dict) else {}
    output: dict[str, list[dict[str, Any]]] = {}
    for slot in ("input", "mechanism", "outcome", "measurement"):
        refs = _source_text_handoff_refs(source.get(slot))
        if refs:
            output[slot] = refs
    return output


def _compact_causal_field_provenance(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    output: dict[str, dict[str, Any]] = {}
    for field in ("input", "mediator", "outcome"):
        item = source.get(field) if isinstance(source.get(field), dict) else {}
        if not item:
            continue
        output[field] = {
            "value": _compact_text(item.get("value")),
            "candidate": _compact_text(item.get("candidate")),
            "source_status": _compact_text(item.get("source_status")),
            "source_unit_ids": _unique_strings(item.get("source_unit_ids")),
            "source_text_handoff_refs": _source_text_handoff_refs(item.get("source_text_handoff_refs")),
            "reason": _compact_text(item.get("reason")),
        }
    return output


def _mechanism_source_span_ref(item: Any) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    return {
        "source": _compact_text(source.get("source")),
        "field": _compact_text(source.get("field")),
        "paper_id": _compact_text(source.get("paper_id")),
        "source_unit_id": _compact_text(source.get("source_unit_id")),
        "source_text_handoff_id": _compact_text(source.get("source_text_handoff_id")),
        "excerpt_hash": _compact_text(source.get("excerpt_hash")),
        "source_field": _compact_text(source.get("source_field")),
        "source_status": _compact_text(source.get("source_status")),
    }


def _mechanism_source_span_refs(values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        ref = _mechanism_source_span_ref(item)
        key = (
            str(ref.get("field") or ""),
            str(ref.get("source_unit_id") or ""),
            str(ref.get("source_text_handoff_id") or ""),
            str(ref.get("excerpt_hash") or ""),
        )
        if not (key[1] or key[2] or key[3]) or key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs


def _field_entry(bundle: dict[str, Any], role: str) -> dict[str, Any]:
    chain = bundle.get("causal_chain") if isinstance(bundle.get("causal_chain"), dict) else {}
    entry = chain.get(role) if isinstance(chain.get(role), dict) else {}
    provenance = bundle.get("causal_field_provenance") if isinstance(bundle.get("causal_field_provenance"), dict) else {}
    provenance_entry = provenance.get(role) if isinstance(provenance.get(role), dict) else {}
    value = _compact_text(
        entry.get("value")
        or provenance_entry.get("value")
    )
    legacy_ids = _unique_strings(
        list(entry.get("fragment_ids") or [])
        + list(provenance_entry.get("source_unit_ids") or [])
    )
    return {"value": value, "legacy_fragment_ids": legacy_ids}


def _legacy_fragment_map(fragments: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in fragments:
        fragment_id = str(item.get("fragment_id") or "")
        legacy_id = str(item.get("legacy_source_unit_id") or "")
        if fragment_id:
            mapping[fragment_id] = fragment_id
        if fragment_id and legacy_id:
            mapping[legacy_id] = fragment_id
    return mapping


def _refs_for_role(
    role: str,
    field: dict[str, Any],
    fragments: list[dict[str, Any]],
) -> list[str]:
    mapping = _legacy_fragment_map(fragments)
    refs = [mapping[item] for item in field.get("legacy_fragment_ids", []) if item in mapping]
    if not refs:
        refs = [
            str(item.get("fragment_id") or "")
            for item in fragments
            if role in set(item.get("supported_roles") or [])
            and item.get("evidence_category") == "primary"
        ]
    ranked = sorted(
        (item for item in fragments if str(item.get("fragment_id") or "") in set(refs)),
        key=lambda item: (-float(item.get("score") or 0.0), str(item.get("fragment_id") or "")),
    )
    return [str(item["fragment_id"]) for item in ranked[:MAX_FRAGMENT_REFS_PER_SLOT]]


def _category_refs(fragments: list[dict[str, Any]], category: str) -> list[str]:
    return [
        str(item["fragment_id"])
        for item in sorted(
            (item for item in fragments if item.get("evidence_category") == category),
            key=lambda item: (-float(item.get("score") or 0.0), str(item.get("fragment_id") or "")),
        )[:MAX_FRAGMENT_REFS_PER_SLOT]
    ]


def _artifact_version(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return max(1, default)


def _versioned_ref(kind: str, gap_id: str, version: int) -> str:
    return f"{kind}/{gap_id}/v{int(version):04d}.json"


def build_mechanism_evidence_bundle_artifact(
    project_id: str,
    gap_id: str,
    bundle: dict[str, Any],
    fragments: list[dict[str, Any]],
    *,
    bundle_version: int,
    run_id: str,
) -> dict[str, Any]:
    source = bundle if isinstance(bundle, dict) else {}
    fields = {role: _field_entry(source, role) for role in ("input", "mediator", "outcome")}
    is_restricted_bridge = bool(
        source.get("restricted_component_bridge_gap") is True
        or "RESTRICTED_COMPONENT_BRIDGE" in _compact_text(source.get("status")).upper()
    )
    missing_requirements = _unique_strings(source.get("missing_requirements"))
    if is_restricted_bridge:
        for role in ("input", "mediator", "outcome"):
            if not _compact_text(fields[role].get("value")):
                requirement = f"{role}_role_contract_missing"
                if requirement not in missing_requirements:
                    missing_requirements.append(requirement)
        if not _compact_text(source.get("comparison")):
            requirement = "comparison_role_contract_missing"
            if requirement not in missing_requirements:
                missing_requirements.append(requirement)
        status = _compact_text(source.get("status") or "UNRESOLVED")
        if missing_requirements:
            status = "RESTRICTED_COMPONENT_BRIDGE_ROLE_CONTRACT_INCOMPLETE"
    else:
        status = _compact_text(source.get("status") or "UNRESOLVED")
    design = source.get("research_design_evidence") if isinstance(source.get("research_design_evidence"), dict) else {}
    supporting = list(dict.fromkeys(
        _refs_for_role("input", fields["input"], fragments)
        + _refs_for_role("mediator", fields["mediator"], fragments)
        + _refs_for_role("outcome", fields["outcome"], fragments)
    ))[:MAX_FRAGMENT_REFS_PER_SLOT]
    source_text_handoff_refs = _source_text_handoff_refs(source.get("source_text_handoffs"))
    accepted_handoff_refs = _source_text_handoff_refs(source.get("accepted_source_text_handoffs"))
    rejected_handoff_refs = _source_text_handoff_refs(source.get("rejected_source_text_handoffs"))
    slot_lineage_refs = _slot_source_lineage_refs(source.get("slot_source_lineage"))
    compact_provenance = _compact_causal_field_provenance(source.get("causal_field_provenance"))
    mechanism_source_span_refs = _mechanism_source_span_refs(source.get("mechanism_source_spans"))
    evidence_lineage_refs = _source_text_handoff_refs(source.get("evidence_lineage"))
    if not evidence_lineage_refs:
        evidence_lineage_refs = source_text_handoff_refs
    artifact = {
        "schema_version": MECHANISM_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "project_id": _compact_text(project_id),
        "gap_id": _compact_text(gap_id),
        "bundle_version": _artifact_version(bundle_version),
        "status": status,
        "missing_requirements": missing_requirements,
        "input": {"value": fields["input"]["value"], "fragment_refs": _refs_for_role("input", fields["input"], fragments)},
        "mediator": {"value": fields["mediator"]["value"], "fragment_refs": _refs_for_role("mediator", fields["mediator"], fragments)},
        "outcome": {"value": fields["outcome"]["value"], "fragment_refs": _refs_for_role("outcome", fields["outcome"], fragments)},
        "theory_evidence_refs": _unique_strings(source.get("theory_evidence_ids")),
        "experimental_evidence_refs": _unique_strings(source.get("experimental_evidence_ids")),
        "computational_evidence_refs": _unique_strings(source.get("computational_evidence_ids")),
        "competing_fragment_refs": _category_refs(fragments, "competing"),
        "rejected_audit_fragment_refs": _category_refs(fragments, "rejected"),
        "research_design_evidence": {
            "recommended_mode": _compact_text(design.get("recommended_mode") or source.get("research_mode") or "UNRESOLVED_RESEARCH_DESIGN"),
            "status": _compact_text(design.get("status") or "UNSUPPORTED"),
            "supporting_fragment_count": len(supporting),
            "supporting_fragment_refs": supporting,
            "full_audit_ref": f"audits/fragment_candidates/{_compact_text(run_id)}.jsonl",
        },
        "source_text_handoff_refs": source_text_handoff_refs,
        "accepted_source_text_handoff_refs": accepted_handoff_refs,
        "rejected_source_text_handoff_refs": rejected_handoff_refs,
        "slot_source_lineage": slot_lineage_refs,
        "causal_field_provenance": compact_provenance,
        "mechanism_source_span_refs": mechanism_source_span_refs,
        "accepted_source_lineage": slot_lineage_refs,
        "rejected_source_lineage": rejected_handoff_refs,
        "evidence_lineage_refs": evidence_lineage_refs,
        "source_lineage_status": (
            "SOURCE_TEXT_HANDOFF_BOUND"
            if accepted_handoff_refs or any(slot_lineage_refs.values())
            else "SOURCE_TEXT_HANDOFF_MISSING"
        ),
    }
    result = _with_content_hash(artifact)
    validate_normalized_artifact(result)
    return result


def _gap_causal_value(bundle: dict[str, Any], role: str) -> str:
    bundle_field = bundle.get(role) if isinstance(bundle.get(role), dict) else {}
    return _compact_text(bundle_field.get("value"))


def build_gap_artifact(
    project_id: str,
    gap: dict[str, Any],
    bundle_artifact: dict[str, Any],
    fragments: list[dict[str, Any]],
    *,
    gap_version: int,
    contract_version: int,
) -> dict[str, Any]:
    gap_id = _compact_text(gap.get("gap_id"))
    bundle_version = _artifact_version(bundle_artifact.get("bundle_version"))
    source_audit = gap.get("original_source_role_audit") if isinstance(gap.get("original_source_role_audit"), dict) else {}
    source_snapshot_hash = _compact_text(
        gap.get("source_snapshot_hash")
        or source_audit.get("audit_hash")
        or gap.get("gap_snapshot_hash")
    )
    if not source_snapshot_hash:
        source_snapshot_hash = _json_hash({
            "gap_id": gap_id,
            "sub_hypothesis_id": gap.get("sub_hypothesis_id"),
            "description": gap.get("description"),
            "source_evidence_units": gap.get("source_evidence_units") or gap.get("supporting_references"),
        })
    claim = gap.get("gap_claim") if isinstance(gap.get("gap_claim"), dict) else {}
    verification_scope = claim.get("verification_scope") if isinstance(claim.get("verification_scope"), dict) else {}
    gap_handoff_refs = _source_text_handoff_refs(gap.get("source_text_handoffs"))
    if not gap_handoff_refs:
        gap_handoff_refs = _source_text_handoff_refs(gap.get("source_evidence_units"))
    if not gap_handoff_refs:
        gap_handoff_refs = list(bundle_artifact.get("source_text_handoff_refs") or [])
    gap_evidence_lineage_refs = _source_text_handoff_refs(gap.get("evidence_lineage"))
    if not gap_evidence_lineage_refs:
        gap_evidence_lineage_refs = gap_handoff_refs
    assertion_ids = _unique_strings(
        gap.get("assertion_ids")
        or gap.get("source_assertion_ids")
        or (gap.get("evidence_graph_contract") or {}).get("assertion_ids")
    )
    slot_support_ids = _unique_strings(
        gap.get("slot_support_ids")
        or [
            item.get("slot_support_id")
            for item in gap_handoff_refs
            if isinstance(item, dict)
        ]
    )
    reportable = bool(
        gap.get("reportable") is True
        or _compact_text(gap.get("status")).upper() == "REPORTABLE_GAP"
        or _compact_text(gap.get("acceptance_status")).upper() == "REPORTABLE"
        or _compact_text(claim.get("claim_level")).upper() == "REPORTABLE_GAP"
    )
    lineage_resolved = bool(
        gap_evidence_lineage_refs
        and all(
            _compact_text(item.get("assertion_id"))
            and _compact_text(item.get("source_span_id") or item.get("source_unit_id"))
            and _compact_text(item.get("document_version_hash"))
            and _compact_text(item.get("exact_quote"))
            for item in gap_evidence_lineage_refs
            if isinstance(item, dict)
        )
    )
    if reportable and (not assertion_ids or not slot_support_ids or not lineage_resolved):
        raise ScienceArtifactValidationError(
            "REPORTABLE_GAP requires assertion IDs, slot-support IDs, and source-resolved evidence lineage"
        )
    artifact = {
        "schema_version": SCIENCE_GAP_SCHEMA_VERSION,
        "project_id": _compact_text(project_id),
        "gap_id": gap_id,
        "gap_version": _artifact_version(gap_version),
        "sub_hypothesis_id": _compact_text(gap.get("sub_hypothesis_id")),
        "description": _compact_text(gap.get("description") or gap.get("claim")),
        "gap_type": _compact_text(gap.get("gap_type") or gap.get("type")),
        "source_clue_role": _compact_text(
            gap.get("source_clue_role")
        ),
        "research_mode": _compact_text(
            gap.get("research_mode")
            or bundle_artifact.get("research_design_evidence", {}).get("recommended_mode")
        ),
        "input": _gap_causal_value(bundle_artifact, "input"),
        "mediator": _gap_causal_value(bundle_artifact, "mediator"),
        "outcome": _gap_causal_value(bundle_artifact, "outcome"),
        "comparison": _compact_text(gap.get("comparison")),
        "falsification": _compact_text(gap.get("falsification")),
        "input_fragment_refs": list(bundle_artifact.get("input", {}).get("fragment_refs") or [])[:MAX_FRAGMENT_REFS_PER_SLOT],
        "mediator_fragment_refs": list(bundle_artifact.get("mediator", {}).get("fragment_refs") or [])[:MAX_FRAGMENT_REFS_PER_SLOT],
        "outcome_fragment_refs": list(bundle_artifact.get("outcome", {}).get("fragment_refs") or [])[:MAX_FRAGMENT_REFS_PER_SLOT],
        "competing_fragment_refs": _category_refs(fragments, "competing"),
        "rejected_audit_fragment_refs": _category_refs(fragments, "rejected"),
        "evidence_bundle_ref": _versioned_ref("bundles", gap_id, bundle_version),
        "latest_contract_ref": _versioned_ref("contracts", gap_id, _artifact_version(contract_version)),
        "source_snapshot_hash": source_snapshot_hash,
        # Gap v2 transports a compact statement boundary rather than the full
        # discovery object.  This lets an exported artifact say whether it is
        # source-stated, corpus-bounded, externally verified, or merely an
        # opportunity without embedding raw retrieval results or excerpts.
        "candidate_identity": _compact_text(gap.get("candidate_identity")),
        "claim_level": _compact_text(claim.get("claim_level")),
        "claim_statement": _compact_text(claim.get("statement")),
        "claim_verification_verdict": _compact_text(claim.get("verification_verdict")),
        "claim_last_verified_at": claim.get("last_verified_at") or "",
        "claim_requires_external_verification": claim.get("requires_external_verification") is True,
        "claim_scope_kind": _compact_text(verification_scope.get("scope_kind")),
        "source_text_handoff_refs": gap_handoff_refs,
        "evidence_lineage_refs": gap_evidence_lineage_refs,
        "assertion_ids": assertion_ids,
        "slot_support_ids": slot_support_ids,
        "source_lineage_status": (
            "SOURCE_TEXT_HANDOFF_BOUND" if gap_handoff_refs else "SOURCE_TEXT_HANDOFF_MISSING"
        ),
    }
    result = _with_content_hash(artifact)
    validate_normalized_artifact(result)
    return result


def _contract_missing_requirements(contract: dict[str, Any]) -> list[str]:
    readiness = contract.get("hypothesis_readiness") if isinstance(contract.get("hypothesis_readiness"), dict) else {}
    return _unique_strings(
        contract.get("missing_requirements")
        or readiness.get("missing_requirements")
        or contract.get("remaining_unresolved")
    )


def build_socrates_contract_artifact(
    project: dict[str, Any],
    gap_artifact: dict[str, Any],
    bundle_artifact: dict[str, Any],
    contract: dict[str, Any],
    *,
    contract_version: int,
) -> dict[str, Any]:
    gap_id = str(gap_artifact.get("gap_id") or "")
    artifact = {
        "schema_version": SOCRATES_CONTRACT_SCHEMA_VERSION,
        "project_id": str(gap_artifact.get("project_id") or project.get("project_id") or ""),
        "gap_id": gap_id,
        "contract_version": _artifact_version(contract_version),
        "gap_ref": f"gaps/{gap_id}.json",
        "gap_snapshot_hash": str(gap_artifact.get("content_hash") or ""),
        "evidence_bundle_ref": str(gap_artifact.get("evidence_bundle_ref") or ""),
        "evidence_bundle_hash": str(bundle_artifact.get("content_hash") or ""),
        "contract_status": _compact_text(contract.get("contract_status") or contract.get("verdict") or "UNRESOLVED"),
        "missing_requirements": _contract_missing_requirements(contract),
        # This is the version at which this contract was created, not the
        # version of every later unrelated project save.  Preserving it keeps
        # normalized contracts immutable when only project metadata changes.
        "created_at_state_version": int(
            contract.get("created_at_state_version")
            or contract.get("project_version")
            or project.get("state_version")
            or 0
        ),
    }
    result = _with_content_hash(artifact)
    validate_normalized_artifact(result)
    return result


def build_socrates_report_artifact(
    project_id: str,
    run_id: str,
    gap_id: str,
    report: dict[str, Any],
    *,
    contract_version: int,
) -> dict[str, Any]:
    readiness = report.get("hypothesis_readiness") if isinstance(report.get("hypothesis_readiness"), dict) else {}
    artifact = {
        "schema_version": SOCRATES_REPORT_SCHEMA_VERSION,
        "project_id": _compact_text(project_id),
        "run_id": _compact_text(run_id),
        "gap_id": _compact_text(gap_id),
        "contract_ref": _versioned_ref("contracts", gap_id, _artifact_version(contract_version)),
        "verdict": _compact_text(report.get("verdict") or report.get("contract_status") or "UNRESOLVED"),
        "search_count": int(report.get("searches") or report.get("search_count") or 0),
        "import_count": int(report.get("imports") or report.get("import_count") or 0),
        "missing_requirements": _unique_strings(
            report.get("missing_requirements")
            or report.get("remaining_unresolved")
            or readiness.get("missing_requirements")
        ),
        "query_audit_ref": f"audits/socrates_queries/{_compact_text(run_id)}.jsonl",
    }
    result = _with_content_hash(artifact)
    validate_normalized_artifact(result)
    return result


def _collect_bundle_fragments(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("evidence_fragment_alignments", "gap_anchor_fragment_alignments"):
        values = bundle.get(key)
        if isinstance(values, list):
            candidates.extend(item for item in values if isinstance(item, dict))
    design = bundle.get("research_design_evidence") if isinstance(bundle.get("research_design_evidence"), dict) else {}
    values = design.get("fragment_alignments")
    if isinstance(values, list):
        candidates.extend(item for item in values if isinstance(item, dict))
    return candidates


def _latest_socrates_report(project: dict[str, Any], gap_id: str) -> dict[str, Any]:
    return next((
        item for item in reversed(project.get("socrates_reports", []))
        if isinstance(item, dict) and str(item.get("gap_id") or "") == gap_id
    ), {})


def build_normalized_gap_artifact_set(
    project: dict[str, Any],
    gap: dict[str, Any],
    *,
    run_id: str,
    gap_version: int | None = None,
    bundle_version: int | None = None,
    contract_version: int | None = None,
) -> dict[str, Any]:
    """Build a complete reference-only gap artifact set without persistence."""
    project_id = _compact_text(project.get("project_id"))
    gap_id = _compact_text(gap.get("gap_id"))
    normalized_run_id = _compact_text(run_id)
    if not project_id or not gap_id or not normalized_run_id:
        raise ScienceArtifactValidationError("Normalized gap artifact set requires project_id, gap_id, and run_id")
    source_bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    fragment_result = deduplicate_and_prune_fragments(_collect_bundle_fragments(source_bundle))
    fragments = fragment_result["selected_fragments"]
    resolved_gap_version = _artifact_version(gap_version or gap.get("gap_revision") or gap.get("gap_version"))
    resolved_bundle_version = _artifact_version(bundle_version or source_bundle.get("bundle_version") or resolved_gap_version)
    current_contract = (
        (project.get("socrates_mechanism_contracts") or {}).get(gap_id)
        if isinstance(project.get("socrates_mechanism_contracts"), dict)
        else {}
    )
    current_contract = current_contract if isinstance(current_contract, dict) else {}
    resolved_contract_version = _artifact_version(
        contract_version or current_contract.get("contract_version") or current_contract.get("gap_revision")
    )
    bundle_artifact = build_mechanism_evidence_bundle_artifact(
        project_id,
        gap_id,
        source_bundle,
        fragments,
        bundle_version=resolved_bundle_version,
        run_id=normalized_run_id,
    )
    gap_artifact = build_gap_artifact(
        project_id,
        gap,
        bundle_artifact,
        fragments,
        gap_version=resolved_gap_version,
        contract_version=resolved_contract_version,
    )
    contract_artifact = build_socrates_contract_artifact(
        project,
        gap_artifact,
        bundle_artifact,
        current_contract,
        contract_version=resolved_contract_version,
    )
    report_artifact = build_socrates_report_artifact(
        project_id,
        normalized_run_id,
        gap_id,
        _latest_socrates_report(project, gap_id),
        contract_version=resolved_contract_version,
    )
    return {
        "schema_version": NORMALIZED_GAP_ARTIFACT_SET_SCHEMA_VERSION,
        "project_id": project_id,
        "gap_id": gap_id,
        "run_id": normalized_run_id,
        "gap": gap_artifact,
        "bundle": bundle_artifact,
        "contract": contract_artifact,
        "report": report_artifact,
        "canonical_fragments": fragments,
        "fragment_candidate_audit_records": fragment_result["audit_records"],
        "fragment_statistics": fragment_result["statistics"],
    }


def _walk_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}.{key}"
            if key in _FORBIDDEN_EMBEDDED_KEYS:
                violations.append(child)
            violations.extend(_walk_forbidden_keys(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(_walk_forbidden_keys(nested, f"{path}[{index}]"))
    return violations


def validate_normalized_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise ScienceArtifactValidationError("Normalized artifact must be an object")
    schema = str(artifact.get("schema_version") or "")
    allowed_by_schema = {
        SCIENCE_GAP_LEGACY_SCHEMA_VERSION: _GAP_V1_ALLOWED_KEYS,
        SCIENCE_GAP_SCHEMA_VERSION: _GAP_ALLOWED_KEYS,
        MECHANISM_EVIDENCE_BUNDLE_SCHEMA_VERSION: _BUNDLE_ALLOWED_KEYS,
        SOCRATES_CONTRACT_SCHEMA_VERSION: _CONTRACT_ALLOWED_KEYS,
        SOCRATES_REPORT_SCHEMA_VERSION: _REPORT_ALLOWED_KEYS,
        CANONICAL_FRAGMENT_SCHEMA_VERSION: _FRAGMENT_ALLOWED_KEYS,
    }
    allowed = allowed_by_schema.get(schema)
    if allowed is None:
        raise ScienceArtifactValidationError(f"Unknown normalized artifact schema: {schema or '<missing>'}")
    unexpected = sorted(set(artifact) - allowed)
    if unexpected:
        raise ScienceArtifactValidationError(
            f"{schema} contains non-schema fields: {', '.join(unexpected)}"
        )
    required_by_schema = {
        SCIENCE_GAP_LEGACY_SCHEMA_VERSION: (
            "project_id", "gap_id", "gap_version", "evidence_bundle_ref",
            "latest_contract_ref", "source_snapshot_hash", "content_hash",
        ),
        SCIENCE_GAP_SCHEMA_VERSION: (
            "project_id", "gap_id", "gap_version", "evidence_bundle_ref",
            "latest_contract_ref", "source_snapshot_hash", "content_hash",
        ),
        MECHANISM_EVIDENCE_BUNDLE_SCHEMA_VERSION: (
            "project_id", "gap_id", "bundle_version", "status", "content_hash",
        ),
        SOCRATES_CONTRACT_SCHEMA_VERSION: (
            "project_id", "gap_id", "contract_version", "gap_ref", "gap_snapshot_hash",
            "evidence_bundle_ref", "evidence_bundle_hash", "contract_status", "content_hash",
        ),
        SOCRATES_REPORT_SCHEMA_VERSION: (
            "project_id", "run_id", "gap_id", "contract_ref", "verdict", "content_hash",
        ),
        CANONICAL_FRAGMENT_SCHEMA_VERSION: (
            "fragment_id", "paper_id", "alignment_contract_hash", "source_field",
            "excerpt", "excerpt_hash", "content_hash",
        ),
    }
    missing = [key for key in required_by_schema[schema] if artifact.get(key) in {None, ""}]
    if missing:
        raise ScienceArtifactValidationError(
            f"{schema} is missing required fields: {', '.join(missing)}"
        )
    violations = _walk_forbidden_keys(artifact)
    if violations:
        raise ScienceArtifactValidationError(
            f"{schema} embeds forbidden recursive objects: {', '.join(violations[:10])}"
        )
    if schema != CANONICAL_FRAGMENT_SCHEMA_VERSION and "excerpt" in json.dumps(artifact, ensure_ascii=False):
        # Key-specific traversal above catches known fragment containers; this
        # final guard prevents a newly named embedded excerpt field from
        # quietly entering gap/bundle/contract/report artifacts.
        def has_excerpt_key(value: Any) -> bool:
            if isinstance(value, dict):
                return "excerpt" in value or any(has_excerpt_key(item) for item in value.values())
            if isinstance(value, list):
                return any(has_excerpt_key(item) for item in value)
            return False
        if has_excerpt_key(artifact):
            raise ScienceArtifactValidationError(f"{schema} may not embed fragment excerpts")
    for key, value in artifact.items():
        if key.endswith("fragment_refs") and isinstance(value, list) and len(value) > MAX_FRAGMENT_REFS_PER_SLOT:
            raise ScienceArtifactValidationError(f"{schema}.{key} exceeds top-{MAX_FRAGMENT_REFS_PER_SLOT}")
        if key.endswith("fragment_refs") and isinstance(value, list) and any(
            not str(item).startswith("frag_") for item in value
        ):
            raise ScienceArtifactValidationError(f"{schema}.{key} contains a non-canonical fragment reference")
        if isinstance(value, dict):
            refs = value.get("fragment_refs")
            if isinstance(refs, list) and len(refs) > MAX_FRAGMENT_REFS_PER_SLOT:
                raise ScienceArtifactValidationError(f"{schema}.{key}.fragment_refs exceeds top-{MAX_FRAGMENT_REFS_PER_SLOT}")
            if isinstance(refs, list) and any(not str(item).startswith("frag_") for item in refs):
                raise ScienceArtifactValidationError(f"{schema}.{key}.fragment_refs contains a non-canonical reference")
    if not str(artifact.get("content_hash") or "").startswith("sha256:"):
        raise ScienceArtifactValidationError(f"{schema} content_hash must use sha256")
    expected_hash = artifact_content_hash(artifact)
    if artifact.get("content_hash") != expected_hash:
        raise ScienceArtifactValidationError(f"{schema} content_hash mismatch")
    return {
        "valid": True,
        "schema_version": schema,
        "content_hash": expected_hash,
    }
