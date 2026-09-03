"""Constrained qwen3-vl-plus perception for explicitly supplied data only."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.llm.vision import QwenVisionClient, resolve_vision_settings
from src.llm.structured_output import StructuredOutputError

from .contract import MultimodalInputError, MultimodalInputSpec
from .rendering import PreviewRenderError, render_png_preview, supports_remote_preview
from .runtime_logging import get_multimodal_logger, safe_exception_summary
from .safety import violates_noncausal_policy


QWEN3_VL_PLUS = "qwen3-vl-plus"
logger = get_multimodal_logger()
_FOCUS_ALIASES = {
    "trend_or_distribution": "boundary",
    "mechanism_or_process": "mechanism",
    "response_or_outcome": "mechanism",
    "comparison_or_difference": "contradiction",
    "measurement_or_proxy": "measurement",
    "boundary_or_heterogeneity": "boundary",
}
_FOCUSES = (
    "mechanism", "measurement", "boundary", "contradiction", "theory",
    *tuple(_FOCUS_ALIASES),
)
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
    max_repair_attempts: int = 1,
    max_preview_pixels: int,
    max_preview_bytes: int,
    client_factory: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    """Return validated observation cards without retaining previews or raw replies."""

    if not bool(local_context.get("remote_perception_authorized")):
        logger.info("Remote perception skipped: authorization is false")
        return [], [], {}
    if max_calls < 1:
        raise MultimodalInputError("max_vl_calls must be at least 1 when remote perception is enabled.")
    if max_repair_attempts < 0:
        raise MultimodalInputError("max_vl_repair_attempts cannot be negative.")
    settings = _resolve_pinned_vision_settings(config)
    logger.info(
        "Remote perception started: provider=%s model=%s max_calls=%d",
        settings["provider"],
        settings["model"],
        max_calls,
    )
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
    logger.info(
        "Remote perception candidates selected: selected=%d previewable=%d candidates=%d modalities=%s",
        len(selected_records),
        len(previewable_records),
        len(candidates),
        ",".join(sorted({record.modality for record in candidates})) or "none",
    )
    observations: list[dict[str, Any]] = []
    limitations: list[str] = []
    sent_record_ids: list[str] = []
    primary_call_count = 0
    total_call_count = 0
    for record in candidates:
        if primary_call_count >= max_calls:
            break
        primary_call_count += 1
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
            logger.warning(
                "Preview rendering skipped: record=%s modality=%s reason=%s",
                record_id,
                record.modality,
                safe_exception_summary(exc),
            )
            limitations.append(f"Record {record_id} was not sent for remote perception: {exc}")
            continue
        prompt = _observation_prompt(record.modality)
        observation: dict[str, Any] | None = None
        for attempt in range(1, max_repair_attempts + 2):
            total_call_count += 1
            logger.info(
                "Sending sanitized PNG preview: record=%s modality=%s primary=%d/%d total_call=%d repair=%d/%d attempt=%d/%d timeout=%.0fs",
                record_id,
                record.modality,
                primary_call_count,
                max_calls,
                total_call_count,
                max(0, attempt - 1),
                max_repair_attempts,
                attempt,
                max_repair_attempts + 1,
                float(settings["timeout"]),
            )
            try:
                response = client.describe_json(
                    preview,
                    prompt=prompt,
                    schema=OBSERVATION_SCHEMA,
                    media_type="image/png",
                    max_tokens=min(int(settings["max_tokens"]), 1200),
                )
            except StructuredOutputError as exc:
                logger.warning(
                    "Structured observation response invalid: record=%s attempt=%d/%d error=%s",
                    record_id,
                    attempt,
                    max_repair_attempts + 1,
                    safe_exception_summary(exc),
                )
                if attempt <= max_repair_attempts:
                    prompt = _observation_repair_prompt(record.modality, exc)
                    continue
                logger.error(
                    "Remote perception request failed: record=%s error=%s",
                    record_id,
                    safe_exception_summary(exc),
                )
                raise MultimodalInputError(
                    "Remote perception failed for an explicitly authorized preview; no fallback model was used."
                ) from exc
            except Exception as exc:
                logger.error(
                    "Remote perception request failed: record=%s error=%s",
                    record_id,
                    safe_exception_summary(exc),
                )
                raise MultimodalInputError(
                    "Remote perception failed for an explicitly authorized preview; no fallback model was used."
                ) from exc
            if record_id not in sent_record_ids:
                sent_record_ids.append(record_id)
            logger.info(
                "Remote perception response received: record=%s primary=%d/%d total_call=%d attempt=%d/%d",
                record_id,
                primary_call_count,
                max_calls,
                total_call_count,
                attempt,
                max_repair_attempts + 1,
            )
            observation = _sanitize_observation(
                response,
                record_id=record_id,
                modality=record.modality,
            )
            if observation is not None:
                break
            logger.warning(
                "Observation rejected by non-causal policy: record=%s modality=%s attempt=%d/%d",
                record_id,
                record.modality,
                attempt,
                max_repair_attempts + 1,
            )
            if attempt <= max_repair_attempts:
                prompt = _observation_repair_prompt(record.modality)
                continue
            limitations.append(
                f"Record {record_id} returned an observation outside the non-causal claim policy after a bounded repair attempt."
            )
        if observation is None:
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
    logger.info(
        "Remote perception finished: primary_calls=%d total_calls=%d observations=%d deferred=%d limitations=%d",
        primary_call_count,
        total_call_count,
        len(observations),
        max(0, len(candidates) - primary_call_count),
        len(limitations),
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
Return exactly one JSON object matching the JSON schema below. Include every required field exactly as named,
even when the visible evidence is uncertain. Treat only visible preview content as evidence.

Rules:
- Describe a local pattern, not a settled scientific result. Never claim causality, universality, priority, or proof.
- Keep every text field concise and within the schema limits; prefer one or two short sentences per field.
- Every field must satisfy the local non-causal policy. Do not use these bare phrases anywhere: "proves",
  "establishes", "confirms", "demonstrates", "causes", "drives", "leads to", "produces",
  "shows that", "indicates that", or "suggests that". Prefer "the preview contains", "is compatible with",
  "may reflect", and "a competing explanation is".
- Provide a tentative candidate explanation, and set alternative_explanations to a JSON array containing at least one
  competing-explanation string. Also provide one discriminating prediction and one falsifier.
- State clear limits: this is one bounded representative preview and cannot identify people, patients, identities, raw records, or metadata.
- Do not transcribe raw data, infer hidden values, or mention file names or paths.
- Use concise scientific English; use confidence=low unless the visible preview itself is unambiguous.

JSON schema:
{json.dumps(OBSERVATION_SCHEMA, ensure_ascii=False, sort_keys=True)}
"""


def _observation_repair_prompt(
    modality: str,
    error: Exception | None = None,
) -> str:
    validation_detail = f"The previous response failed validation: {error}" if error else "The previous response used disallowed causal wording."
    return f"""You are repairing one observation for an explicitly supplied {modality} record.
{validation_detail}
Return exactly one complete JSON object with every required field in the schema below.
Keep the observation bounded to visible preview content. Do not use bare causal or proof language, including
"proves", "establishes", "confirms", "demonstrates", "causes", "drives", "leads to", "produces",
"shows that", "indicates that", or "suggests that". Use "the preview contains", "is compatible with",
"may reflect", and explicit competing explanations instead. Do not mention paths, filenames, metadata, or raw values.
The previous response exceeded a validation limit or omitted a required key, so rewrite rather than repeat it. Set
alternative_explanations to a JSON array with at least one concise string; never omit that key or return it as null.
Use compact text: keep
finding and candidate_explanation under 450 characters, each alternative under 220 characters, and
discriminating_prediction, falsifier, and claim_limits under 320 characters.

JSON schema:
{json.dumps(OBSERVATION_SCHEMA, ensure_ascii=False, sort_keys=True)}
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
    focus = str(raw.get("focus") or "mechanism").casefold()
    focus = _FOCUS_ALIASES.get(focus, focus)
    if focus not in {"mechanism", "measurement", "boundary", "contradiction", "theory"}:
        focus = "mechanism"
    return {
        "observation_id": "",
        "record_ids": [record_id],
        "modality": modality,
        **normalized,
        "alternative_explanations": alternatives,
        "confidence": str(raw.get("confidence") or "low"),
        "focus": focus,
    }


def _clean_text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]
