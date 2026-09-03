"""Domain-independent retrieval vocabulary for multimodal observations.

The vision model produces explanations in prose, while literature providers
work better with a small set of scientific anchors.  This module converts the
former into the latter without embedding a discipline-specific vocabulary in
the retrieval compiler.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


RETRIEVAL_PROFILE_VERSION = "multimodal_retrieval_profile_v3"
MAX_TERMS_PER_GROUP = 8
MAX_QUERY_TERMS = 10

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
        "can", "could", "for", "from", "has", "have", "in", "into", "is",
        "it", "may", "might", "more", "of", "on", "or", "that", "the", "their",
        "this", "to", "under", "was", "were", "with", "would", "should", "than",
        "then", "there", "these", "those", "through", "during", "after", "before",
        "provided", "local", "bounded", "tentative", "representative", "selected",
        "supplied", "user", "data", "record", "records", "figure", "figures", "image",
        "observation", "observed", "pattern", "visible", "preview", "contains", "shows",
        "show", "depicts", "illustrates", "presents", "compares", "displays", "panel",
        "panels", "three", "two", "one", "multimodal", "maps", "map", "suggests", "suggest",
        "appears", "appear", "likely", "possibly", "compatible", "explanation",
        "evidence", "result", "results", "study", "published", "scientific",
    }
)
_INTERNAL_PHRASES = (
    "observed data pattern",
    "multimodal measurement",
    "mechanism evidence",
    "contradictory evidence",
    "provided-data observation",
    "data-anchored observation",
    "data anchored observation",
    "scientific evidence",
    "published study",
    "preview contains",
    "preview shows",
    "the preview",
    "user supplied",
    "multimodal evidence",
    "scientific literature",
)
_LEADING_BOILERPLATE = re.compile(
    r"^(?:in|from|within)\s+(?:the\s+)?(?:representative|selected|provided|supplied|local|bounded)\s+"
    r"(?:preview|data|record(?:\s+records?)?|observation)[^:]*:\s*",
    re.IGNORECASE,
)
_VISUAL_PREFIX = re.compile(
    r"^(?:the\s+)?(?:preview|figure|panel|image|plot|map|chart)\s+"
    r"(?:contains|shows|depicts|illustrates|presents|compares|displays)\s+",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"[.;:!?\n]+")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9%+/().-]*")
_PANEL_LABEL_RE = re.compile(r"^[A-Za-z]\)$")


def build_retrieval_profile(
    claim: Mapping[str, Any] | None,
    project_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact, auditable retrieval anchors for one multimodal claim."""

    claim_data = _mapping(claim)
    context = _mapping(project_context)
    operationalization = _mapping(context.get("academic_operationalization"))
    domain_context = _mapping(context.get("domain_context"))

    candidate = _values(claim_data.get("candidate_explanation"))
    alternatives = _values(claim_data.get("alternative_explanations"))
    finding = _values(claim_data.get("local_data_statement"))
    prediction = _values(claim_data.get("discriminating_prediction"))
    falsifier = _values(claim_data.get("falsifier"))
    research_object = _values(
        operationalization.get("research_object"),
        context.get("original_topic"),
    )
    if not research_object:
        research_object = _values(context.get("core_entities"))[:2]
    synonyms = _values(
        claim_data.get("retrieval_synonyms"),
        claim_data.get("aliases"),
    )
    if not synonyms and not (candidate or finding):
        synonyms = _values(
            domain_context.get("retrieval_terms"),
            context.get("retrieval_synonyms"),
            context.get("retrieval_plan", {}).get("include_anchors")
            if isinstance(context.get("retrieval_plan"), Mapping)
            else None,
        )
    scope = _values(context.get("research_objective"), context.get("original_objective"))
    methods = _values(
        context.get("method_or_design"),
        context.get("dataset_or_corpus"),
    )

    entity_terms = _compact_many([*research_object, *synonyms], limit=MAX_TERMS_PER_GROUP)
    phenomenon_terms = _compact_many([*research_object, *candidate, *finding], limit=MAX_TERMS_PER_GROUP)
    variable_terms = _classify_phrases([*candidate, *finding], _VARIABLE_HINTS)
    condition_terms = _classify_phrases([*prediction, *finding], _CONDITION_HINTS)
    comparison_terms = _compact_many([*alternatives, *falsifier], limit=MAX_TERMS_PER_GROUP)
    outcome_terms = _compact_many([*finding, *candidate], limit=MAX_TERMS_PER_GROUP)
    measurement_terms = _classify_phrases(
        [*candidate, *finding, *methods], _MEASUREMENT_HINTS
    )
    method_terms = _classify_phrases([*methods, *prediction], _METHOD_HINTS)
    dataset_terms = _compact_many(
        [context.get("dataset_id"), context.get("dataset_or_corpus")], limit=MAX_TERMS_PER_GROUP
    )
    time_scale_terms = _compact_many(
        [context.get("time_or_scale"), context.get("temporal_scope"), *scope], limit=4
    )
    space_scale_terms = _compact_many(
        [context.get("space_or_scale"), context.get("spatial_scope"), *scope], limit=4
    )
    uncertainty_terms = _compact_many(
        [claim_data.get("claim_limits"), *falsifier], limit=MAX_TERMS_PER_GROUP
    )

    groups = {
        "phenomenon_terms": phenomenon_terms,
        "entity_terms": entity_terms,
        "variable_terms": variable_terms,
        "condition_terms": condition_terms,
        "comparison_terms": comparison_terms,
        "outcome_terms": outcome_terms,
        "measurement_terms": measurement_terms,
        "method_terms": method_terms,
        "dataset_terms": dataset_terms,
        "time_scale_terms": time_scale_terms,
        "space_scale_terms": space_scale_terms,
        "aliases": _compact_many(synonyms, limit=MAX_TERMS_PER_GROUP),
        "uncertainty_terms": uncertainty_terms,
    }
    return {
        "profile_version": RETRIEVAL_PROFILE_VERSION,
        "source": RETRIEVAL_PROFILE_VERSION,
        **groups,
        "all_anchor_terms": _unique(
            [term for values in groups.values() for term in values], limit=MAX_TERMS_PER_GROUP * 2
        ),
    }


def build_profile_query_variants(
    profile: Mapping[str, Any],
    *,
    role: str = "construct",
    support: bool = True,
) -> list[dict[str, Any]]:
    """Build short variants for a scientific retrieval role.

    ``support`` changes only the epistemic metadata and alternative anchor
    selection.  The scientific anchor space remains shared by both directions.
    """

    profile_data = _mapping(profile)
    role_name = _normalize_role(role)
    base = _unique(
        [
            *_group(profile_data, "phenomenon_terms"),
            *_group(profile_data, "entity_terms"),
        ],
        limit=4,
    )
    candidates = {
        "construct": [*base, *_group(profile_data, "outcome_terms"), *_group(profile_data, "variable_terms")],
        "mechanism": [*base, *_group(profile_data, "variable_terms"), *_group(profile_data, "condition_terms")],
        "proxy_or_measure": [*base, *_group(profile_data, "variable_terms"), *_group(profile_data, "measurement_terms")],
        "reference_or_target_measure": [*_group(profile_data, "outcome_terms"), *_group(profile_data, "measurement_terms"), *_group(profile_data, "method_terms")],
        "mapping_or_calibration": [*_group(profile_data, "variable_terms"), *_group(profile_data, "measurement_terms"), *_group(profile_data, "condition_terms")],
        "alternative_explanation": [*base, *_group(profile_data, "comparison_terms"), *_group(profile_data, "outcome_terms")],
        "boundary_condition": [*base, *_group(profile_data, "condition_terms"), *_group(profile_data, "space_scale_terms"), *_group(profile_data, "time_scale_terms")],
        "replication": [*base, *_group(profile_data, "outcome_terms"), *_group(profile_data, "method_terms")],
    }
    terms = _bounded_term_list(candidates.get(role_name, candidates["construct"]))
    secondary = _bounded_term_list(
        [
            *_group(profile_data, "aliases"),
            *_group(profile_data, "measurement_terms"),
            *_group(profile_data, "outcome_terms"),
        ],
    )
    variants = []
    for index, values in enumerate((terms, _bounded_term_list([*base, *secondary])), start=1):
        if not values:
            continue
        variants.append(
            {
                "variant_id": f"{role_name}_{'support' if support else 'counter'}_{index:02d}",
                "query_terms": values,
                "purpose": f"{role_name} literature validation",
                "epistemic_role": "support" if support else "alternative_explanation",
                "evidence_mode": "mechanism" if role_name == "mechanism" else "empirical",
                "source": RETRIEVAL_PROFILE_VERSION,
                "profile_version": RETRIEVAL_PROFILE_VERSION,
                "query_quality_warnings": [],
            }
        )
    return variants


def _normalize_role(value: Any) -> str:
    text = str(value or "construct").strip().casefold().replace(" ", "_")
    return text if text in {
        "construct", "mechanism", "proxy_or_measure", "reference_or_target_measure",
        "mapping_or_calibration", "alternative_explanation", "boundary_condition", "replication",
    } else "construct"


def _group(profile: Mapping[str, Any], key: str) -> list[str]:
    return [item for item in _values(profile.get(key)) if item]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _values(*values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = list(value.values())
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            output.extend(_values(*value))
        elif value is not None:
            item = _clean_phrase(value)
            if item:
                output.append(item)
    return _unique(output, limit=24)


def _clean_phrase(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    text = _LEADING_BOILERPLATE.sub("", text)
    for phrase in _INTERNAL_PHRASES:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    text = _VISUAL_PREFIX.sub("", text)
    pieces = _SPLIT_RE.split(text, maxsplit=1)
    text = pieces[0].strip(" ,()[]{}")
    tokens = _TOKEN_RE.findall(text)
    meaningful = [
        token
        for token in tokens
        if token.casefold() not in _STOPWORDS and not _PANEL_LABEL_RE.fullmatch(token)
    ]
    if not meaningful:
        cjk_text = re.sub(r"[，。；：！？、]+", " ", text).strip()
        if re.search(r"[\u3400-\u9fff]", cjk_text):
            return cjk_text[:48]
        return ""
    cleaned = " ".join(meaningful[:7])
    if _is_generic_context_phrase(cleaned):
        return ""
    return cleaned


def _compact_many(values: Sequence[Any], *, limit: int) -> list[str]:
    return _unique([_clean_phrase(value) for value in values], limit=limit)


def _unique(values: Sequence[Any], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_phrase(value)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _bounded_term_list(values: Sequence[Any]) -> list[str]:
    """Prefer informative phrases while keeping a query near 8–12 words."""

    candidates = _unique(values, limit=MAX_QUERY_TERMS * 2)
    # A longer phrase already carries its shorter component (for example,
    # ``thermal stress response`` carries ``stress response``).  Dropping the
    # component prevents an otherwise useful query from becoming repetitive.
    selected: list[str] = []
    for item in sorted(candidates, key=lambda value: (-len(value.split()), candidates.index(value))):
        normalized = item.casefold()
        if any(normalized != existing.casefold() and normalized in existing.casefold() for existing in selected):
            continue
        selected.append(item)
    selected.sort(key=lambda value: candidates.index(value))
    bounded: list[str] = []
    word_count = 0
    for item in selected:
        item_words = len(item.split())
        if bounded and word_count + item_words > 12:
            continue
        bounded.append(item)
        word_count += item_words
        if len(bounded) >= MAX_QUERY_TERMS:
            break
    return bounded or candidates[:2]


_VARIABLE_HINTS = ("variable", "concentration", "rate", "level", "signal", "stress", "temperature", "humidity", "pressure", "intensity", "slope", "response")
_CONDITION_HINTS = ("condition", "under", "during", "after", "before", "matched", "regime", "treatment", "environment", "scale")
_MEASUREMENT_HINTS = ("measure", "measurement", "proxy", "assay", "imaging", "signal", "index", "curve", "spectrum", "concentration", "rate", "calibrat")
_METHOD_HINTS = ("method", "model", "experiment", "observation", "dataset", "calibrat", "validation", "measurement", "simulation", "survey")


_GENERIC_CONTEXT_PHRASES = frozenset(
    {
        "unresolved research domain",
        "identify task object condition limitation boundaries",
        "research design inventory v1",
        "research object",
        "project studies",
        "which research objects tasks deployment",
    }
)


def _is_generic_context_phrase(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    return normalized in _GENERIC_CONTEXT_PHRASES or normalized.startswith("identify task object")


def _classify_phrases(values: Sequence[Any], hints: Sequence[str]) -> list[str]:
    phrases = _compact_many(values, limit=MAX_TERMS_PER_GROUP)
    selected = [item for item in phrases if any(hint in item.casefold() for hint in hints)]
    return _unique([*selected, *phrases], limit=MAX_TERMS_PER_GROUP)


__all__ = [
    "MAX_QUERY_TERMS",
    "RETRIEVAL_PROFILE_VERSION",
    "build_profile_query_variants",
    "build_retrieval_profile",
]
