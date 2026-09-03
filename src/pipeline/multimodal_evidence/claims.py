"""Convert constrained observations into a non-causal multimodal claim ledger."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .safety import violates_noncausal_policy


_FOCUS_ALIASES = {
    "trend_or_distribution": "boundary",
    "mechanism_or_process": "mechanism",
    "response_or_outcome": "mechanism",
    "comparison_or_difference": "contradiction",
    "measurement_or_proxy": "measurement",
    "boundary_or_heterogeneity": "boundary",
}


def build_claim_ledger(
    observations: Sequence[Mapping[str, Any]],
    native_findings: Sequence[Mapping[str, Any]],
    *,
    maximum_claims: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return normalized observation cards, admissible claims, and limitations.

    An observation can become a claim only when it is tied to a successful
    local finding and states both an alternative explanation and a falsifier.
    """

    native_ids = {
        str(item.get("record_id"))
        for item in native_findings
        if isinstance(item, Mapping) and item.get("status") == "success"
    }
    normalized_observations: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    limitations: list[str] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        record_ids = [
            str(record_id)
            for record_id in observation.get("record_ids", [])
            if str(record_id) in native_ids
        ]
        if not record_ids:
            limitations.append("A remote observation was excluded because it had no successful local record binding.")
            continue
        normalized = _normalized_observation(observation, record_ids=record_ids)
        if normalized is None:
            limitations.append(
                f"Observation for record {record_ids[0]} was excluded by the non-causal claim policy."
            )
            continue
        normalized["observation_id"] = f"mme:obs:{len(normalized_observations) + 1:03d}"
        normalized_observations.append(normalized)
        if len(claims) >= maximum_claims:
            continue
        claim = _claim_from_observation(normalized)
        if claim is None:
            limitations.append(
                f"Observation {normalized['observation_id']} lacks the competing-explanation or falsifier detail required for a claim."
            )
            continue
        claim["claim_id"] = f"mme:claim:{len(claims) + 1:03d}"
        claims.append(claim)
    return normalized_observations, claims, limitations


def _normalized_observation(
    observation: Mapping[str, Any],
    *,
    record_ids: list[str],
) -> dict[str, Any] | None:
    text_fields = (
        "finding",
        "candidate_explanation",
        "discriminating_prediction",
        "falsifier",
        "claim_limits",
    )
    normalized = {key: _text(observation.get(key), limit=700) for key in text_fields}
    alternatives = [
        _text(item, limit=400)
        for item in observation.get("alternative_explanations", [])
        if _text(item, limit=400)
    ][:3]
    if not all(normalized.values()) or not alternatives:
        return None
    if any(violates_noncausal_policy(item) for item in [*normalized.values(), *alternatives]):
        return None
    focus = _text(observation.get("focus"), limit=40).casefold()
    focus = _FOCUS_ALIASES.get(focus, focus)
    if focus not in {"mechanism", "measurement", "boundary", "contradiction", "theory"}:
        focus = "mechanism"
    confidence = _text(observation.get("confidence"), limit=20).casefold()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "record_ids": record_ids,
        "modality": _text(observation.get("modality"), limit=40),
        **normalized,
        "alternative_explanations": alternatives,
        "confidence": confidence,
        "focus": focus,
    }


def _claim_from_observation(observation: Mapping[str, Any]) -> dict[str, Any] | None:
    alternative = _text((observation.get("alternative_explanations") or [""])[0], limit=400)
    falsifier = _text(observation.get("falsifier"), limit=500)
    limits = _text(observation.get("claim_limits"), limit=500)
    if not alternative or not falsifier or not limits:
        return None
    finding = _text(observation.get("finding"), limit=700)
    candidate = _text(observation.get("candidate_explanation"), limit=700)
    record_ids = list(observation.get("record_ids") or [])
    return {
        "observation_id": observation["observation_id"],
        "record_ids": record_ids,
        "local_data_statement": (
            "In the representative preview of the provided data record(s) "
            f"{', '.join(record_ids)}, the bounded observation was: {finding}. "
            "This is a local data statement, not an established scientific result."
        ),
        "candidate_explanation": candidate,
        "alternative_explanations": list(observation.get("alternative_explanations") or []),
        "discriminating_prediction": _text(
            observation.get("discriminating_prediction"), limit=500
        ),
        "falsifier": falsifier,
        "claim_limits": (
            f"{limits} It is compatible with the candidate explanation but cannot distinguish "
            "competing explanations without external evidence."
        ),
        "confidence": observation.get("confidence", "low"),
        "focus": observation.get("focus", "mechanism"),
    }


def _text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]
