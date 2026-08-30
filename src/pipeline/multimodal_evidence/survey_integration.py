"""Safe multimodal projections shared by Survey publication and Idea loading.

The runtime evidence contract intentionally stays independent from Survey and
Idea schemas.  This module adds only bounded, path-free metadata needed to
link a data-anchored SH to its observations, literature search intent, and
downstream handoff artifacts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import MultimodalInputError, validate_multimodal_evidence
from .data_sh_compiler import DATA_ANCHORED_PRIORITY
from .query_binding import normalize_query_variant_bindings


MULTIMODAL_SURVEY_PROJECTION_SCHEMA_VERSION = "multimodal_survey_projection_v1"
LOCAL_DATA_OBSERVATION = "LOCAL_DATA_OBSERVATION"

_DATA_SH_ID_PATTERN = re.compile(r"^MM_SH_[0-9]{2}$")
_RECONCILIATION_STATUSES = frozenset(
    {
        "supported_within_scope",
        "challenged",
        "mixed",
        "unresolved",
        "measurement_at_risk",
    }
)


def enrich_multimodal_evidence(
    evidence: Mapping[str, Any],
    *,
    data_anchored_subhypothesis_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return validated evidence plus safe SH linkage and conservative reconciliation.

    Search intent is useful context, but it is not a literature adjudication.
    Therefore this first publication stage records every linked claim as
    ``unresolved`` until an explicit semantic/full-text reconciliation path
    supplies paper-level assessments in a later stage.
    """

    normalized = validate_multimodal_evidence(evidence)
    artifact = _mapping(data_anchored_subhypothesis_artifact)
    metadata = _validated_data_sh_metadata(
        artifact.get("metadata_by_subhypothesis"),
        observations=normalized.get("observations"),
        claims=normalized.get("claims"),
    )
    if not metadata:
        return normalized

    bindings = normalize_query_variant_bindings(
        artifact.get("query_variant_bindings") or []
    )
    linked_bindings = [
        binding
        for binding in bindings
        if binding["sub_hypothesis_id"] in metadata
    ]
    reconciliation = _build_literature_reconciliation(metadata, linked_bindings)
    enriched = {
        **normalized,
        "data_anchored_subhypotheses": metadata,
        "query_variant_bindings": linked_bindings,
        "literature_reconciliation": reconciliation,
    }
    return validate_multimodal_evidence(enriched)


def build_multimodal_survey_projection(
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project data-anchored observations for a prompt or handoff.

    The returned object excludes file paths, raw media, previews, provider
    output, and unbounded native-analysis payloads.  It contains only the
    observation/claim information a downstream scientific writer can cite as
    supplied local data rather than as literature.
    """

    if not isinstance(evidence, Mapping) or not evidence:
        return None
    normalized = validate_multimodal_evidence(evidence)
    metadata = _validated_data_sh_metadata(
        normalized.get("data_anchored_subhypotheses"),
        observations=normalized.get("observations"),
        claims=normalized.get("claims"),
    )
    if not metadata:
        return None
    raw_observations = normalized.get("observations")
    observations = {
        _text(item.get("observation_id"), limit=120): {
            **_mapping(item),
            "_source_index": index,
        }
        for index, item in enumerate(raw_observations if isinstance(raw_observations, list) else [])
        if isinstance(item, Mapping) and _text(item.get("observation_id"), limit=120)
    }
    claims = {
        _text(item.get("claim_id"), limit=120): _mapping(item)
        for item in _records(normalized.get("claims"))
        if _text(item.get("claim_id"), limit=120)
    }
    reconciliation = {
        _text(item.get("claim_id"), limit=120): _safe_reconciliation(item)
        for item in _records(normalized.get("literature_reconciliation"))
        if _text(item.get("claim_id"), limit=120)
    }
    input_summary = _mapping(normalized.get("input_summary"))
    sample_scope = {
        "validated_record_count": _safe_positive_int(
            input_summary.get("validated_record_count")
        ),
        "selected_record_count": _safe_positive_int(
            input_summary.get("selected_record_count")
        ),
        "successful_local_analysis_count": _safe_positive_int(
            input_summary.get("successful_local_analysis_count")
        ),
        "available_by_modality": _safe_count_mapping(
            input_summary.get("available_by_modality")
        ),
        "selected_by_modality": _safe_count_mapping(
            input_summary.get("selected_by_modality")
        ),
    }
    rows: list[dict[str, Any]] = []
    for subhypothesis_id, item in metadata.items():
        claim_rows = []
        for claim_id in item["claim_ids"]:
            claim = claims.get(claim_id)
            if not claim:
                continue
            claim_rows.append(
                {
                    "claim_id": claim_id,
                    "observation_id": _text(claim.get("observation_id"), limit=120),
                    "local_data_statement": _text(
                        claim.get("local_data_statement"), limit=900
                    ),
                    "candidate_explanation": _text(
                        claim.get("candidate_explanation"), limit=500
                    ),
                    "alternative_explanations": _texts(
                        claim.get("alternative_explanations"), limit=400, maximum=3
                    ),
                    "discriminating_prediction": _text(
                        claim.get("discriminating_prediction"), limit=500
                    ),
                    "falsifier": _text(claim.get("falsifier"), limit=500),
                    "claim_limits": _text(claim.get("claim_limits"), limit=700),
                    "confidence": _text(claim.get("confidence"), limit=24),
                    "focus": _text(claim.get("focus"), limit=48),
                    "literature_reconciliation": reconciliation.get(
                        claim_id,
                        _unresolved_reconciliation(claim_id, []),
                    ),
                }
            )
        observation_rows = []
        for observation_id in item["observation_ids"]:
            observation = observations.get(observation_id)
            if not observation:
                continue
            observation_rows.append(
                {
                    "observation_id": observation_id,
                    "source_index": observation.get("_source_index"),
                    "record_ids": _texts(
                        observation.get("record_ids"), limit=120, maximum=12
                    ),
                    "modality": _text(observation.get("modality"), limit=48),
                    "finding": _text(observation.get("finding"), limit=900),
                    "candidate_explanation": _text(
                        observation.get("candidate_explanation"), limit=500
                    ),
                    "alternative_explanations": _texts(
                        observation.get("alternative_explanations"),
                        limit=400,
                        maximum=3,
                    ),
                    "claim_limits": _text(observation.get("claim_limits"), limit=700),
                }
            )
        if not claim_rows or not observation_rows:
            continue
        rows.append(
            {
                "sub_hypothesis_id": subhypothesis_id,
                "analysis_priority": DATA_ANCHORED_PRIORITY,
                "must_cover": True,
                "question_kind": item["question_kind"],
                "claim_ids": list(item["claim_ids"]),
                "observation_ids": list(item["observation_ids"]),
                "sample_scope": sample_scope,
                "observations": observation_rows,
                "claims": claim_rows,
            }
        )
    if not rows:
        return None
    return {
        "schema_version": MULTIMODAL_SURVEY_PROJECTION_SCHEMA_VERSION,
        "dataset_id": _text(normalized.get("dataset_id"), limit=120),
        "perception_mode": _text(
            _mapping(normalized.get("perception")).get("mode"), limit=48
        ),
        "data_anchored_subhypotheses": rows,
    }


def multimodal_trace_details(
    plan_entry: Mapping[str, Any],
    observation_id: Any,
) -> dict[str, Any] | None:
    """Resolve one observation only when it belongs to the traced data SH."""

    projection = _mapping(plan_entry).get("multimodal_projection")
    observation_key = _text(observation_id, limit=120)
    if not isinstance(projection, Mapping) or not observation_key:
        return None
    owned_observations = _texts(projection.get("observation_ids"), limit=120)
    if observation_key not in owned_observations:
        return None
    observation = next(
        (
            _mapping(item)
            for item in _records(projection.get("observations"))
            if _text(item.get("observation_id"), limit=120) == observation_key
        ),
        None,
    )
    if not observation:
        return None
    linked_claims = [
        _mapping(item)
        for item in _records(projection.get("claims"))
        if _text(item.get("observation_id"), limit=120) == observation_key
    ]
    limits = _texts(
        [
            observation.get("claim_limits"),
            *[claim.get("claim_limits") for claim in linked_claims],
        ],
        limit=700,
        maximum=4,
    )
    return {
        "observation_id": observation_key,
        "claim_ids": _texts(
            [claim.get("claim_id") for claim in linked_claims], limit=120, maximum=3
        ),
        "claim_limits": limits,
    }


def _validated_data_sh_metadata(
    raw_metadata: Any,
    *,
    observations: Any,
    claims: Any,
) -> dict[str, dict[str, Any]]:
    if raw_metadata is None:
        return {}
    if not isinstance(raw_metadata, Mapping):
        raise MultimodalInputError("Data-anchored SH metadata must be an object.")
    observation_ids = {
        _text(item.get("observation_id"), limit=120)
        for item in _records(observations)
        if _text(item.get("observation_id"), limit=120)
    }
    claims_by_id = {
        _text(item.get("claim_id"), limit=120): _mapping(item)
        for item in _records(claims)
        if _text(item.get("claim_id"), limit=120)
    }
    metadata: dict[str, dict[str, Any]] = {}
    for raw_identifier, raw_value in raw_metadata.items():
        identifier = _text(raw_identifier, limit=120)
        item = _mapping(raw_value)
        if not _DATA_SH_ID_PATTERN.fullmatch(identifier):
            raise MultimodalInputError("Data-anchored SH identifiers must use MM_SH_01 style.")
        if item.get("analysis_priority") != DATA_ANCHORED_PRIORITY:
            raise MultimodalInputError(
                f"Data-anchored SH '{identifier}' must retain DATA_ANCHORED_PRIMARY priority."
            )
        claim_ids = _texts(item.get("claim_ids"), limit=120, maximum=3)
        observation_ids_for_sh = _texts(item.get("observation_ids"), limit=120, maximum=3)
        question_kind = _text(item.get("question_kind"), limit=96)
        if not claim_ids or not observation_ids_for_sh or not question_kind:
            raise MultimodalInputError(
                f"Data-anchored SH '{identifier}' requires claim, observation, and question-kind metadata."
            )
        if any(claim_id not in claims_by_id for claim_id in claim_ids):
            raise MultimodalInputError(
                f"Data-anchored SH '{identifier}' references an unknown multimodal claim."
            )
        if any(observation_id not in observation_ids for observation_id in observation_ids_for_sh):
            raise MultimodalInputError(
                f"Data-anchored SH '{identifier}' references an unknown multimodal observation."
            )
        if any(
            _text(claims_by_id[claim_id].get("observation_id"), limit=120)
            not in observation_ids_for_sh
            for claim_id in claim_ids
        ):
            raise MultimodalInputError(
                f"Data-anchored SH '{identifier}' must own every observation linked by its claims."
            )
        metadata[identifier] = {
            "analysis_priority": DATA_ANCHORED_PRIORITY,
            "claim_ids": claim_ids,
            "observation_ids": observation_ids_for_sh,
            "question_kind": question_kind,
        }
    return metadata


def _build_literature_reconciliation(
    metadata: Mapping[str, Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        by_claim.setdefault(_text(binding.get("claim_id"), limit=120), []).append(
            _mapping(binding)
        )
    rows: list[dict[str, Any]] = []
    for item in metadata.values():
        for claim_id in item["claim_ids"]:
            rows.append(_unresolved_reconciliation(claim_id, by_claim.get(claim_id, [])))
    return rows


def _unresolved_reconciliation(
    claim_id: str,
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    roles = {
        _text(binding.get("epistemic_role"), limit=80).casefold()
        for binding in bindings
    }
    return {
        "claim_id": claim_id,
        "search_coverage": {
            "support_attempted": "support" in roles,
            "counter_attempted": bool(roles & {"counter", "boundary"}),
            "alternative_attempted": "alternative_explanation" in roles,
            "measurement_attempted": "measurement_confound" in roles,
        },
        "status": "unresolved",
        "paper_assessments": [],
        "permitted_statement": (
            "Describe only the bounded supplied-data observation as compatible with "
            "a tentative explanation; keep competing explanations and external "
            "literature verification explicit."
        ),
        "forbidden_statement": (
            "Do not describe the supplied data as proving, establishing, or "
            "generalizing a mechanism, and do not present it as a literature citation."
        ),
    }


def _safe_reconciliation(value: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(value)
    status = _text(item.get("status"), limit=64)
    if status not in _RECONCILIATION_STATUSES:
        status = "unresolved"
    coverage = _mapping(item.get("search_coverage"))
    return {
        "status": status,
        "search_coverage": {
            "support_attempted": bool(coverage.get("support_attempted")),
            "counter_attempted": bool(coverage.get("counter_attempted")),
            "alternative_attempted": bool(coverage.get("alternative_attempted")),
            "measurement_attempted": bool(coverage.get("measurement_attempted")),
        },
        "paper_assessments": [
            _safe_paper_assessment(item)
            for item in _records(item.get("paper_assessments"))[:12]
        ],
        "permitted_statement": _text(item.get("permitted_statement"), limit=700),
        "forbidden_statement": _text(item.get("forbidden_statement"), limit=700),
    }


def _safe_paper_assessment(value: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "paper_id": _text(item.get("paper_id"), limit=160),
        "assessment": _text(item.get("assessment"), limit=500),
        "claim_limits": _texts(item.get("claim_limits"), limit=400, maximum=3),
    }


def _safe_count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        label = _text(key, limit=64)
        count = _safe_positive_int(raw_count)
        if label and count is not None:
            result[label] = count
    return result


def _safe_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _texts(value: Any, *, limit: int, maximum: int = 12) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _text(raw, limit=limit)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
        if len(result) >= maximum:
            break
    return result


def _text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


__all__ = [
    "LOCAL_DATA_OBSERVATION",
    "MULTIMODAL_SURVEY_PROJECTION_SCHEMA_VERSION",
    "build_multimodal_survey_projection",
    "enrich_multimodal_evidence",
    "multimodal_trace_details",
]
