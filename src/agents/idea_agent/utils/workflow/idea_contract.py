"""Canonical idea-contract normalization and legacy alias migration helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.pipeline.discipline_taxonomy import canonicalize_discipline_key


LEGACY_IDEA_ALIASES = {
    "core_contribute": "core_contribution",
    "methodology": "method",
}

IDEA_CONTRACT_FIELDS = (
    "title",
    "abstract",
    "core_contribution",
    "method",
    "risks",
    "tags",
    "operator",
    "target_defects",
    "rationale",
    "memory_refs",
    "components",
    "component_explanations",
    "root_domains",
    "discipline_resolution",
    "scientific_intervention",
    "paper_graph_context",
    "edit_plan",
    "skill_metrics",
    "direction_mode",
    "direction_summary",
    "central_hypothesis",
    "scientific_object",
    "mechanism_or_relation",
    "intervention_or_transformation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "target_gap_ids",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
)

MATURE_IDEA_FIELDS = (
    "idea_id",
    "title",
    "abstract",
    "hypothesis",
    "central_hypothesis",
    "scientific_object",
    "mechanism",
    "mechanism_or_relation",
    "intervention_or_transformation",
    "assumptions",
    "evidence_basis",
    "target_gap_ids",
    "gap_alignment",
    "refinement_scope",
    "falsifier",
    "maturity_status",
    "maturity",
    "maturity_is_not_rank",
    "idea_source",
    "lineage",
    "source_lineage",
    "route_signature",
    "independence_rationale",
    "independence_status",
    "counterexamples",
    "negative_evidence",
    "retrieval_queries",
    "mechanism_chain",
    "validation_targets",
    "anchor_policy",
    "anti_anchor",
    "anti_anchor_reason",
    "reframed_problem_id",
    "rejected_gap_ids",
)

_MATURE_SOURCE_ALIASES = {
    "survey": "survey_gap",
    "history": "prior_candidate",
    "prior": "prior_candidate",
    "experiment": "experiment_feedback",
    "generated": "problem_reframing",
    "adversarial": "adversarial_generation",
    "cross_domain": "cross_domain_transfer",
}

_REQUIRED_TEXT_FIELDS = (
    "title",
    "abstract",
    "core_contribution",
    "method",
)


def _cmp_key(value: Any) -> str:
    return str(value).strip()


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_optional_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key).strip(): item for key, item in value.items() if str(key).strip()}
    if isinstance(value, (list, tuple)):
        return [dict(item) if isinstance(item, Mapping) else str(item).strip() for item in value]
    if value is None:
        return ""
    return str(value).strip()


def _as_root_domains(value: Any) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for item in _as_list(value):
        canonical_key = canonicalize_discipline_key(item)
        if not canonical_key or canonical_key in seen:
            continue
        seen.add(canonical_key)
        normalized.append(canonical_key)
    return normalized[:2]


def _as_str_dict(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _as_lineage_list(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(item) if isinstance(item, Mapping) else str(item).strip() for item in value if item not in (None, "")]
    if value not in (None, ""):
        return [str(value).strip()]
    return []


def normalize_idea_contract(
    payload: Any,
    *,
    allow_legacy: bool = False,
    keep_extra: bool = False,
) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("Idea contract must be a mapping.")

    raw = dict(payload)
    raw.pop("experiments", None)
    raw.pop("experiment_design", None)
    for legacy_key, canonical_key in LEGACY_IDEA_ALIASES.items():
        if legacy_key not in raw:
            continue
        if not allow_legacy:
            raise ValueError(f"Legacy idea key is not allowed: {legacy_key}")
        legacy_value = raw.pop(legacy_key)
        if canonical_key in raw and _cmp_key(raw[canonical_key]) != _cmp_key(legacy_value):
            raise ValueError(f"Conflicting idea fields: {canonical_key} vs {legacy_key}")
        raw.setdefault(canonical_key, legacy_value)

    idea = {
        "title": _as_text(raw.get("title")),
        "abstract": _as_text(raw.get("abstract")),
        "core_contribution": _as_text(raw.get("core_contribution")),
        "method": _as_text(raw.get("method")),
        "risks": _as_text(raw.get("risks")),
        "tags": _as_list(raw.get("tags")),
        "operator": _as_text(raw.get("operator")),
        "target_defects": _as_list(raw.get("target_defects")),
        "rationale": _as_text(raw.get("rationale")),
        "memory_refs": _as_list(raw.get("memory_refs")),
        "components": _as_list(raw.get("components")),
        "component_explanations": _as_str_dict(raw.get("component_explanations")),
        "root_domains": _as_root_domains(raw.get("root_domains")),
        "discipline_resolution": _as_dict(raw.get("discipline_resolution")),
        "scientific_intervention": _as_dict(raw.get("scientific_intervention")),
        "paper_graph_context": _as_text(raw.get("paper_graph_context")),
        "edit_plan": raw.get("edit_plan") if isinstance(raw.get("edit_plan"), Mapping) else None,
        "skill_metrics": _as_dict(raw.get("skill_metrics")),
        "direction_mode": _as_text(raw.get("direction_mode")),
        "direction_summary": _as_text(raw.get("direction_summary")),
        "central_hypothesis": _as_text(raw.get("central_hypothesis")),
        "scientific_object": _as_dict(raw.get("scientific_object")),
        "mechanism_or_relation": _as_text(raw.get("mechanism_or_relation")),
        "intervention_or_transformation": _as_text(raw.get("intervention_or_transformation")),
        "expected_mechanism": _as_text(raw.get("expected_mechanism")),
        "discriminating_observation": _as_text(raw.get("discriminating_observation")),
        "boundary_or_failure_condition": _as_text(raw.get("boundary_or_failure_condition")),
        "claim_scope": _as_text(raw.get("claim_scope")),
        "assumptions": _as_list(raw.get("assumptions")),
        "target_gap_ids": _as_list(raw.get("target_gap_ids")),
        "gap_alignment": _as_optional_payload(raw.get("gap_alignment")),
        "evidence_requirement": _as_text(raw.get("evidence_requirement")),
        "evidence_basis": _as_optional_payload(raw.get("evidence_basis")),
    }
    missing = [field for field in _REQUIRED_TEXT_FIELDS if not idea[field]]
    if missing:
        raise ValueError(f"Idea contract missing required fields: {', '.join(missing)}")

    if not keep_extra:
        return idea

    extras = {key: value for key, value in raw.items() if key not in IDEA_CONTRACT_FIELDS}
    return {**idea, **extras}


def _as_flexible_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            try:
                decoded = json.loads(stripped)
            except (TypeError, ValueError):
                decoded = None
            if decoded is not None and decoded != value:
                return _as_flexible_list(decoded)
        return [value]
    if isinstance(value, (bytes, Mapping)):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def _mature_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:48] or "idea"


def _mature_text(record: Mapping[str, Any]) -> str:
    for key in ("hypothesis", "central_hypothesis", "abstract", "title"):
        value = _as_text(record.get(key))
        if value:
            return value
    return ""


def normalize_mature_idea(
    value: Any,
    *,
    index: int = 0,
    default_source: str = "user_input",
) -> Dict[str, Any]:
    """Normalize a mature idea record without imposing a domain-specific schema."""

    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        text = _as_text(value)
        raw = {"title": text, "abstract": text, "hypothesis": text}

    title = _as_text(raw.get("title")) or _as_text(raw.get("name"))
    abstract = _as_text(raw.get("abstract")) or _as_text(raw.get("description"))
    hypothesis = _as_text(raw.get("hypothesis")) or _as_text(raw.get("central_hypothesis"))
    central_hypothesis = _as_text(raw.get("central_hypothesis")) or hypothesis
    if not abstract:
        abstract = hypothesis or title
    if not hypothesis:
        hypothesis = central_hypothesis or abstract
    if not title:
        title = (hypothesis or abstract or f"mature idea {index + 1}").split(".", 1)[0].strip()

    raw_id = _as_text(raw.get("idea_id")) or _as_text(raw.get("seed_id"))
    idea_id = raw_id or f"mature-{index + 1:02d}-{_mature_slug(title)}"
    mechanism = _as_text(raw.get("mechanism")) or _as_text(raw.get("mechanism_or_relation"))
    mechanism_or_relation = _as_text(raw.get("mechanism_or_relation")) or mechanism
    object_value = raw.get("scientific_object")
    if isinstance(object_value, Mapping):
        scientific_object: Any = dict(object_value)
    elif object_value is None:
        scientific_object = {}
    else:
        scientific_object = _as_text(object_value)

    lineage = raw.get("lineage")
    if isinstance(lineage, Mapping):
        lineage_value: Any = dict(lineage)
    elif isinstance(lineage, (list, tuple)):
        lineage_value = _as_lineage_list(lineage)
    else:
        lineage_value = _as_text(lineage) or default_source

    route_signature = raw.get("route_signature")
    if route_signature is None:
        route_signature = {
            "scientific_object": scientific_object,
            "mechanism": mechanism_or_relation,
            "intervention": _as_text(raw.get("intervention_or_transformation")),
            "target_gap_ids": _as_list(raw.get("target_gap_ids")),
        }
    elif isinstance(route_signature, Mapping):
        route_signature = dict(route_signature)
    else:
        route_signature = _as_text(route_signature)

    source = _as_text(raw.get("idea_source")) or default_source
    source = _MATURE_SOURCE_ALIASES.get(source.casefold(), source)
    return {
        "idea_id": idea_id,
        "title": title,
        "abstract": abstract,
        "hypothesis": hypothesis,
        "central_hypothesis": central_hypothesis,
        "scientific_object": scientific_object,
        "mechanism": mechanism,
        "mechanism_or_relation": mechanism_or_relation,
        "intervention_or_transformation": _as_text(raw.get("intervention_or_transformation")),
        "assumptions": _as_list(raw.get("assumptions")),
        "evidence_basis": _as_optional_payload(raw.get("evidence_basis")),
        "target_gap_ids": _as_list(raw.get("target_gap_ids")),
        "gap_alignment": _as_optional_payload(raw.get("gap_alignment")),
        "refinement_scope": _as_optional_payload(raw.get("refinement_scope")),
        "falsifier": _as_text(raw.get("falsifier")) or _as_text(raw.get("discriminating_observation")),
        "maturity_status": _as_text(raw.get("maturity_status")) or "mature",
        "maturity": dict(raw.get("maturity")) if isinstance(raw.get("maturity"), Mapping) else {},
        "maturity_is_not_rank": bool(raw.get("maturity_is_not_rank", False)),
        "idea_source": source,
        "lineage": lineage_value,
        "source_lineage": _as_lineage_list(raw.get("source_lineage")),
        "route_signature": route_signature,
        "independence_rationale": _as_text(raw.get("independence_rationale")),
        "independence_status": _as_text(raw.get("independence_status")),
        "counterexamples": _as_list(raw.get("counterexamples")),
        "negative_evidence": _as_list(raw.get("negative_evidence")),
        "retrieval_queries": _as_list(raw.get("retrieval_queries")),
        "mechanism_chain": _as_list(raw.get("mechanism_chain")),
        "validation_targets": _as_list(raw.get("validation_targets")),
        "anchor_policy": _as_text(raw.get("anchor_policy")),
        "anti_anchor": bool(raw.get("anti_anchor", False)),
        "anti_anchor_reason": _as_text(raw.get("anti_anchor_reason")),
        "reframed_problem_id": _as_text(raw.get("reframed_problem_id")),
        "rejected_gap_ids": _as_list(raw.get("rejected_gap_ids")),
    }


def normalize_mature_ideas(
    value: Any,
    *,
    legacy_value: Any = None,
    default_source: str = "user_input",
) -> List[Dict[str, Any]]:
    """Return the canonical mature-idea collection, accepting legacy singular input."""

    raw_values = _as_flexible_list(value)
    if not raw_values and legacy_value not in (None, "", []):
        raw_values = _as_flexible_list(legacy_value)
    flattened: List[Any] = []
    for raw_value in raw_values:
        if isinstance(raw_value, Mapping) and "mature_ideas" in raw_value:
            flattened.extend(_as_flexible_list(raw_value.get("mature_ideas")))
        else:
            flattened.append(raw_value)
    raw_values = flattened
    normalized: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_value in enumerate(raw_values):
        record = normalize_mature_idea(raw_value, index=index, default_source=default_source)
        base_id = record["idea_id"]
        idea_id = base_id
        suffix = 2
        while idea_id in seen_ids:
            idea_id = f"{base_id}-{suffix}"
            suffix += 1
        record["idea_id"] = idea_id
        seen_ids.add(idea_id)
        normalized.append(record)
    return normalized


def mature_idea_legacy_text(ideas: Any) -> str:
    records = normalize_mature_ideas(ideas)
    return _mature_text(records[0]) if records else ""
