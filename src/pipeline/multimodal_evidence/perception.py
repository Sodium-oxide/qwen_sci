"""Constrained qwen3-vl-plus perception for explicitly supplied data only."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.llm.vision import QwenVisionClient, resolve_vision_settings

from .contract import MultimodalInputError, MultimodalInputSpec
from .rendering import PreviewRenderError, render_png_preview, supports_remote_preview
from .safety import violates_noncausal_policy


QWEN3_VL_PLUS = "qwen3-vl-plus"
_FOCUSES = ("mechanism", "measurement", "boundary", "contradiction", "theory")
OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "finding": {"type": "string", "minLength": 4, "maxLength": 700},
        "candidate_explanation": {"type": "string", "minLength": 4, "maxLength": 700},
        "alternative_explanations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string", "minLength": 3, "maxLength": 400},
        },
        "discriminating_prediction": {"type": "string", "minLength": 4, "maxLength": 500},
        "falsifier": {"type": "string", "minLength": 4, "maxLength": 500},
        "claim_limits": {"type": "string", "minLength": 8, "maxLength": 500},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "focus": {"type": "string", "enum": list(_FOCUSES)},
    },
    "required": [
        "finding",
        "candidate_explanation",
        "alternative_explanations",
        "discriminating_prediction",
        "falsifier",
        "claim_limits",
        "confidence",
        "focus",
    ],
    "additionalProperties": False,
}


def run_remote_perception(
    *,
    input_spec: MultimodalInputSpec,
    local_context: Mapping[str, Any],
    config: Any,
    max_calls: int,
    max_preview_pixels: int,
    max_preview_bytes: int,
    client_factory: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    """Return validated observation cards without retaining previews or raw replies."""

    if not bool(local_context.get("remote_perception_authorized")):
        return [], [], {}
    if max_calls < 1:
        raise MultimodalInputError("max_vl_calls must be at least 1 when remote perception is enabled.")
    settings = _resolve_pinned_vision_settings(config)
    factory = client_factory or QwenVisionClient
    client = factory(
        model=settings["model"],
        provider=settings["provider"],
        api_key=settings["api_key"],
        base_url=settings["base_url"],
        timeout=settings["timeout"],
        config=config,
    )
    records_by_id = {record.record_id: record for record in input_spec.records}
    findings_by_id = {
        str(finding.get("record_id")): finding
        for finding in local_context.get("native_findings", [])
        if isinstance(finding, Mapping) and finding.get("status") == "success"
    }
    selected_ids = {
        str(record_id)
        for record_id in local_context.get("selected_record_ids", [])
        if str(record_id) in records_by_id and str(record_id) in findings_by_id
    }
    selected_records = [
        record
        for record in sorted(input_spec.records, key=lambda item: item.input_index)
        if record.record_id in selected_ids
    ]
    previewable_records = [
        record for record in selected_records if supports_remote_preview(record)
    ]
    candidates = _representative_preview_records(previewable_records)
    observations: list[dict[str, Any]] = []
    limitations: list[str] = []
    sent_record_ids: list[str] = []
    remote_call_count = 0
    for record in candidates:
        if remote_call_count >= max_calls:
            break
        record_id = record.record_id
        finding = findings_by_id[record_id]
        try:
            preview = render_png_preview(
                record,
                finding,
                max_pixels=max_preview_pixels,
                max_bytes=max_preview_bytes,
            )
        except PreviewRenderError as exc:
            limitations.append(f"Record {record_id} was not sent for remote perception: {exc}")
            continue
        try:
            response = client.describe_json(
                preview,
                prompt=_observation_prompt(record.modality),
                schema=OBSERVATION_SCHEMA,
                media_type="image/png",
                max_tokens=min(int(settings["max_tokens"]), 1200),
            )
        except Exception as exc:
            raise MultimodalInputError(
                "Remote perception failed for an explicitly authorized preview; no fallback model was used."
            ) from exc
        remote_call_count += 1
        sent_record_ids.append(record_id)
        observation = _sanitize_observation(response, record_id=record_id, modality=record.modality)
        if observation is None:
            limitations.append(
                f"Record {record_id} returned an observation outside the non-causal claim policy."
            )
            continue
        observations.append(observation)
    unsupported_modalities = sorted(
        {record.modality for record in selected_records if not supports_remote_preview(record)}
    )
    if unsupported_modalities:
        limitations.append(
            "Selected records for these modalities have no Batch B remote preview and remained local-only: "
            + ", ".join(unsupported_modalities)
        )
    if len(candidates) > max_calls:
        excluded_record_ids = [record.record_id for record in candidates[max_calls:]]
        limitations.append(
            f"Remote perception used the configured budget of {max_calls} stratified cross-modality previews; "
            f"eligible record IDs deferred by budget: {', '.join(excluded_record_ids)}."
        )
    return observations, limitations, {
        "provider": settings["provider"],
        "model": settings["model"],
        "record_ids": sent_record_ids,
    }


def _representative_preview_records(
    records: Sequence[Any],
) -> list[Any]:
    """Round-robin selected records across modalities and metadata strata."""

    by_modality: "OrderedDict[str, list[Any]]" = OrderedDict()
    for record in records:
        by_modality.setdefault(record.modality, []).append(record)
    modality_queues: "OrderedDict[str, list[Any]]" = OrderedDict()
    for modality, modality_records in by_modality.items():
        by_stratum: "OrderedDict[tuple[str, str, str, str], list[Any]]" = OrderedDict()
        for record in modality_records:
            metadata = record.metadata
            stratum = tuple(
                str(metadata.get(key, ""))
                for key in ("label", "group", "condition", "timepoint")
            )
            by_stratum.setdefault(stratum, []).append(record)
        queue: list[Any] = []
        round_index = 0
        while True:
            added = False
            for stratum_records in by_stratum.values():
                if round_index < len(stratum_records):
                    queue.append(stratum_records[round_index])
                    added = True
            if not added:
                break
            round_index += 1
        modality_queues[modality] = queue
    ordered: list[Any] = []
    round_index = 0
    while True:
        added = False
        for queue in modality_queues.values():
            if round_index < len(queue):
                ordered.append(queue[round_index])
                added = True
        if not added:
            return ordered
        round_index += 1


def _resolve_pinned_vision_settings(config: Any) -> dict[str, Any]:
    multimodal = _multimodal_settings(config)
    configured_model = str(multimodal.get("quality_model") or "").strip()
    if configured_model != QWEN3_VL_PLUS:
        raise MultimodalInputError(
            "Remote multimodal perception requires survey.multimodal_evidence.quality_model=qwen3-vl-plus."
        )
    try:
        settings = resolve_vision_settings(config, batch=False)
    except Exception as exc:
        raise MultimodalInputError("Remote vision settings could not be resolved.") from exc
    if str(settings.get("model") or "").strip() != QWEN3_VL_PLUS:
        raise MultimodalInputError(
            "Remote multimodal perception is pinned to qwen3-vl-plus; batch or flash models are not permitted."
        )
    if str(settings.get("provider") or "").strip().casefold() != "qwen":
        raise MultimodalInputError(
            "Remote multimodal perception requires the Qwen provider for qwen3-vl-plus."
        )
    return dict(settings)


def _multimodal_settings(config: Any) -> Mapping[str, Any]:
    survey = config.get("survey") if hasattr(config, "get") and config.get("survey") is not None else config
    settings = survey.get("multimodal_evidence", {}) if hasattr(survey, "get") else {}
    return settings if isinstance(settings, Mapping) or hasattr(settings, "get") else {}


def _observation_prompt(modality: str) -> str:
    return f"""You are reviewing one sanitized PNG preview derived from an explicitly supplied {modality} record.
Return exactly one JSON object matching the provided schema. Treat only visible preview content as evidence.

Rules:
- Describe a local pattern, not a settled scientific result. Never claim causality, universality, priority, or proof.
- Provide a tentative candidate explanation, at least one competing explanation, one discriminating prediction, and one falsifier.
- State clear limits: this is one bounded representative preview and cannot identify people, patients, identities, raw records, or metadata.
- Do not transcribe raw data, infer hidden values, or mention file names or paths.
- Use concise scientific English; use confidence=low unless the visible preview itself is unambiguous.
"""


def _sanitize_observation(
    value: Mapping[str, Any],
    *,
    record_id: str,
    modality: str,
) -> dict[str, Any] | None:
    raw = dict(value)
    text_fields = (
        "finding",
        "candidate_explanation",
        "discriminating_prediction",
        "falsifier",
        "claim_limits",
    )
    normalized = {key: _clean_text(raw.get(key), limit=700) for key in text_fields}
    alternatives = [
        _clean_text(item, limit=400)
        for item in raw.get("alternative_explanations", [])
        if _clean_text(item, limit=400)
    ][:3]
    if not all(normalized.values()) or not alternatives:
        return None
    if any(violates_noncausal_policy(item) for item in [*normalized.values(), *alternatives]):
        return None
    return {
        "observation_id": "",
        "record_ids": [record_id],
        "modality": modality,
        **normalized,
        "alternative_explanations": alternatives,
        "confidence": str(raw.get("confidence") or "low"),
        "focus": str(raw.get("focus") or "mechanism"),
    }


def _clean_text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]
