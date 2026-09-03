from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .contract import (
    MULTIMODAL_EVIDENCE_SCHEMA_VERSION,
    MULTIMODAL_LOCAL_INPUT_CONTEXT_SCHEMA_VERSION,
    MultimodalInputError,
    MultimodalInputSpec,
    MultimodalSettings,
    validate_local_context,
    validate_multimodal_evidence,
)
from .claims import build_claim_ledger
from .native_analysis import NativeAnalysisError, analyze_record
from .perception import run_remote_perception
from .runtime_logging import get_multimodal_logger
from .sampling import select_stratified_records


logger = get_multimodal_logger()


def multimodal_settings_from_config(
    config: Any,
    *,
    remote_perception_authorized: bool,
) -> MultimodalSettings:
    """Resolve the bounded multimodal settings shared by CLI and web entry points."""

    survey = config.get("survey") if hasattr(config, "get") and config.get("survey") is not None else config
    raw_settings = survey.get("multimodal_evidence", {}) if hasattr(survey, "get") else {}
    settings = dict(raw_settings) if isinstance(raw_settings, Mapping) or hasattr(raw_settings, "items") else {}
    settings["remote_perception_authorized"] = remote_perception_authorized
    return MultimodalSettings.from_mapping(settings)


def prepare_multimodal_runtime(
    *,
    input_spec: MultimodalInputSpec,
    config: Any,
    settings: MultimodalSettings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate explicit media, analyze it locally, and build bounded runtime evidence."""

    logger.info(
        "Multimodal runtime preparation started: dataset=%s records=%d remote_perception=%s",
        input_spec.dataset_id,
        len(input_spec.records),
        settings.remote_perception_authorized,
    )
    from .capabilities import preflight_multimodal_capabilities

    preflight_multimodal_capabilities(
        input_spec,
        remote_perception_authorized=settings.remote_perception_authorized,
    )
    local_context = build_local_multimodal_input_context(input_spec, settings=settings)
    runtime_evidence = build_multimodal_evidence(
        input_spec=input_spec,
        config=config,
        local_context=local_context,
    )
    logger.info(
        "Multimodal runtime preparation completed: local_findings=%d observations=%d claims=%d",
        len(local_context.get("native_findings", [])),
        len(runtime_evidence.get("observations", [])),
        len(runtime_evidence.get("claims", [])),
    )
    return local_context or {}, runtime_evidence or {}


def build_local_multimodal_input_context(
    input_spec: MultimodalInputSpec | None,
    *,
    settings: MultimodalSettings | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if input_spec is None:
        return None
    active_settings = (
        settings
        if isinstance(settings, MultimodalSettings)
        else MultimodalSettings.from_mapping(settings)
    )
    sampling = select_stratified_records(
        input_spec.records,
        max_records_per_modality=active_settings.max_records_per_modality,
    )
    logger.info(
        "Local multimodal analysis started: dataset=%s selected=%d/%d remote_perception=%s",
        input_spec.dataset_id,
        len(sampling.records),
        len(input_spec.records),
        active_settings.remote_perception_authorized,
    )
    native_findings: list[dict[str, Any]] = []
    rejected_records: list[dict[str, str]] = []
    for record in sampling.records:
        try:
            native_findings.append(analyze_record(record))
            logger.info(
                "Local analysis completed: record=%s modality=%s",
                record.record_id,
                record.modality,
            )
        except NativeAnalysisError as exc:
            logger.warning(
                "Local analysis rejected: record=%s modality=%s code=%s",
                record.record_id,
                record.modality,
                exc.code,
            )
            rejected_records.append(
                {
                    "record_id": record.record_id,
                    "modality": record.modality,
                    "source_name": record.source_name,
                    "code": exc.code,
                    "message": str(exc),
                }
            )
    if not native_findings:
        logger.error("Local multimodal analysis failed: no selected record completed")
        raise MultimodalInputError(
            "No selected multimodal records completed local native analysis."
        )
    available_by_modality = Counter(record.modality for record in input_spec.records)
    selected_by_modality = Counter(record.modality for record in sampling.records)
    context = {
        "schema_version": MULTIMODAL_LOCAL_INPUT_CONTEXT_SCHEMA_VERSION,
        "mode": "local_only",
        "remote_perception_authorized": active_settings.remote_perception_authorized,
        "dataset_id": input_spec.dataset_id,
        "records": [record.to_safe_context_dict() for record in input_spec.records],
        "selected_record_ids": sampling.selected_record_ids,
        "native_findings": native_findings,
        "rejected_records": rejected_records,
        "input_summary": {
            "input_mode": input_spec.input_mode,
            "validated_record_count": len(input_spec.records),
            "selected_record_count": len(sampling.records),
            "successful_local_analysis_count": len(native_findings),
            "rejected_record_count": len(rejected_records),
            "available_by_modality": dict(sorted(available_by_modality.items())),
            "selected_by_modality": dict(sorted(selected_by_modality.items())),
            "sampling_policy": sampling.policy,
            "truncated_strata_by_modality": sampling.truncated_strata_by_modality,
        },
    }
    validated = validate_local_context(context)
    logger.info(
        "Local multimodal analysis finished: successful=%d rejected=%d",
        len(native_findings),
        len(rejected_records),
    )
    return validated


def build_multimodal_evidence(
    *,
    input_spec: MultimodalInputSpec | None,
    config: Any,
    local_context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build runtime-only evidence; a missing explicit input performs no work."""

    if input_spec is None:
        return None
    context = (
        validate_local_context(local_context)
        if isinstance(local_context, Mapping)
        else build_local_multimodal_input_context(input_spec)
    )
    if context is None:
        return None
    settings = _multimodal_config(config)
    native_findings = list(context.get("native_findings") or [])
    limitations = [
        "Local native analysis is bounded and does not establish scientific causality or generality."
    ]
    observations: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    perception: dict[str, Any] = {"mode": "local_only"}
    logger.info(
        "Multimodal evidence assembly started: native_findings=%d remote_perception=%s",
        len(native_findings),
        bool(context.get("remote_perception_authorized")),
    )
    if bool(context.get("remote_perception_authorized")):
        observations, remote_limitations, provider = run_remote_perception(
            input_spec=input_spec,
            local_context=context,
            config=config,
            max_calls=_positive_int(settings.get("max_vl_calls"), default=8),
            max_repair_attempts=_nonnegative_int(
                settings.get("max_vl_repair_attempts"), default=1
            ),
            max_preview_pixels=_positive_int(settings.get("max_preview_pixels"), default=1_600_000),
            max_preview_bytes=_positive_int(settings.get("max_preview_bytes"), default=4_194_304),
        )
        observations, claims, claim_limitations = build_claim_ledger(
            observations,
            native_findings,
            maximum_claims=min(3, _positive_int(settings.get("max_data_anchored_sh"), default=3)),
        )
        limitations.extend(remote_limitations)
        limitations.extend(claim_limitations)
        perception = {"mode": "remote_perception", **provider}
        logger.info(
            "Remote multimodal evidence assembled: provider=%s model=%s observations=%d claims=%d previews_sent=%d",
            provider.get("provider", "unknown"),
            provider.get("model", "unknown"),
            len(observations),
            len(claims),
            len(provider.get("record_ids", [])),
        )
    else:
        logger.info("Remote perception disabled; keeping multimodal evidence local-only")
    evidence = {
        "schema_version": MULTIMODAL_EVIDENCE_SCHEMA_VERSION,
        "dataset_id": context.get("dataset_id"),
        "perception": perception,
        "input_summary": dict(context.get("input_summary") or {}),
        "native_findings": native_findings,
        "observations": observations,
        "claims": claims,
        "limitations": limitations,
    }
    validated = validate_multimodal_evidence(evidence)
    logger.info(
        "Multimodal evidence assembly finished: mode=%s observations=%d claims=%d",
        validated["perception"]["mode"],
        len(validated["observations"]),
        len(validated["claims"]),
    )
    return validated


def _multimodal_config(config: Any) -> Mapping[str, Any]:
    survey = config.get("survey") if hasattr(config, "get") and config.get("survey") is not None else config
    settings = survey.get("multimodal_evidence", {}) if hasattr(survey, "get") else {}
    return settings if isinstance(settings, Mapping) or hasattr(settings, "get") else {}


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
