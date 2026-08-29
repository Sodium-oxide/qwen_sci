"""Field-neutral ontology for observable, calculable, or provable outcomes."""
from __future__ import annotations

import re
from typing import Any


_GENERIC_EXACT = {
    "", "analysis", "effect", "evidence", "measurement", "method", "outcome",
    "performance", "research", "result", "results", "study", "system output",
}
_GENERIC_TOKENS = {
    "a", "an", "and", "effect", "for", "from", "in", "measurement", "of", "on",
    "outcome", "performance", "result", "results", "the", "to", "under", "with",
}
_OUTCOME_TYPE_HEADS = (
    "accuracy", "abundance", "bound", "coefficient", "concentration", "cross section",
    "distribution", "efficiency", "error", "fidelity", "flux", "frequency", "lifetime",
    "limit", "loss", "probability", "rate", "ratio", "score", "spectrum", "stability",
    "state", "structure", "temperature", "threshold", "time", "topology", "uncertainty",
    "yield", "classification", "existence", "convergence", "significance",
)
_UNITS = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|K|°C|Pa|kPa|MPa|GPa|Hz|s|ms|ns|m|nm|kg|mol|eV|J|W)\b|"
    r"\b(?:95%\s*)?(?:CI|confidence interval)\b)",
    re.IGNORECASE,
)
_EPISTEMIC_METHODS = (
    "literature review", "systematic review", "meta-analysis", "bibliometric", "database search",
)
_EVIDENCE_RESOURCES = (
    "benchmark dataset", "reference dataset", "data repository", "literature corpus",
    "evidence database", "search corpus",
)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> list[str]:
    expanded: list[str] = []
    for token in re.findall(
        r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+./-]*|[\u4e00-\u9fff]{2,}",
        _compact(value).lower(),
    ):
        expanded.append(token)
        expanded.extend(part for part in re.split(r"[+./_-]+", token) if len(part) >= 3)
    return list(dict.fromkeys(expanded))


def _discriminative(value: Any) -> set[str]:
    type_tokens = {
        token for head in _OUTCOME_TYPE_HEADS
        for token in _tokens(head)
    }
    return {
        token for token in _tokens(value)
        if token not in _GENERIC_TOKENS and token not in type_tokens
    }


def _target_alignment(candidate: str, targets: list[str]) -> dict[str, Any]:
    normalized = candidate.lower()
    target_values = [_compact(value) for value in targets if _compact(value)]
    exact = [value for value in target_values if value.lower() in normalized or normalized in value.lower()]
    candidate_terms = _discriminative(candidate)
    matched_terms: set[str] = set()
    for target in target_values:
        matched_terms.update(candidate_terms & _discriminative(target))
    passes = bool(exact or len(matched_terms) >= 2)
    return {
        "passes": passes,
        "exact_or_contained_matches": exact[:6],
        "matched_discriminative_terms": sorted(matched_terms)[:12],
        "target_terms_available": bool(target_values),
    }


def classify_outcome_candidate(
    value: Any,
    *,
    research_mode: str = "",
    target_outcome_terms: list[str] | None = None,
    source_unit_ids: list[str] | None = None,
    require_target_alignment: bool = True,
    require_source_bound: bool = True,
) -> dict[str, Any]:
    """Classify a readout independently from the input/intervention ontology."""
    text = _compact(value)
    lowered = text.lower()
    ids = list(dict.fromkeys(str(item) for item in (source_unit_ids or []) if str(item)))
    targets = [str(item) for item in (target_outcome_terms or []) if str(item).strip()]
    target_alignment = _target_alignment(text, targets)
    type_hits = [head for head in _OUTCOME_TYPE_HEADS if head in lowered]
    discriminative = _discriminative(text)
    unit_signal = bool(_UNITS.search(text))
    base = {
        "version": "outcome_ontology_v1",
        "candidate": text,
        "research_mode": str(research_mode or ""),
        "category": "unresolved",
        "ontology_valid": False,
        "admissible_as_outcome": False,
        "source_bound": bool(ids),
        "source_unit_ids": ids,
        "target_alignment": target_alignment,
        "outcome_type_hits": type_hits,
        "unit_or_interval_signal": unit_signal,
        "discriminative_terms": sorted(discriminative)[:16],
        "reason": "No outcome candidate was supplied.",
    }
    if not text:
        return base
    if (
        lowered in _GENERIC_EXACT
        or any(marker in lowered for marker in _EPISTEMIC_METHODS)
        or any(marker in lowered for marker in _EVIDENCE_RESOURCES)
    ):
        return {
            **base,
            "category": "generic_or_epistemic_output",
            "reason": "A generic result word or evidence-gathering method is not a scientific outcome.",
        }
    compact = len(text) <= 180 and len(text.split()) <= 20
    # A named metric with one scientific object is sufficient; formal outputs
    # such as an error bound may be identified by multiple outcome-type heads.
    specific = bool(
        compact
        and (
            unit_signal
            or len(discriminative) >= 2
            or type_hits and discriminative
            or len(type_hits) >= 2
        )
    )
    target_valid = bool(target_alignment.get("passes") or not require_target_alignment)
    source_valid = bool(ids or not require_source_bound)
    admissible = bool(specific and target_valid and source_valid)
    return {
        **base,
        "category": (
            "observable_or_calculable_or_provable_outcome"
            if specific else "generic_or_unmeasurable_outcome"
        ),
        "ontology_valid": specific,
        "admissible_as_outcome": admissible,
        "reason": (
            "The source-bound outcome is specific and aligned with the sub-hypothesis target."
            if admissible
            else "The outcome lacks a specific metric/state/structure/decision condition."
            if not specific
            else "The outcome is not aligned with the current sub-hypothesis target contract."
            if not target_valid
            else "The outcome lacks a paper-qualified source unit."
        ),
    }
