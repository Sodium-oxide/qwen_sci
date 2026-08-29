"""Strict JSON-only LLM invocation for ExperimentDesign stages."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Optional
from typing import Any

from src.agents.idea_agent.utils.core.response_parsing import (
    JsonObjectResponseError,
    parse_json_object_response,
)
from src.llm.provider_registry import resolve_model


JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
MAX_LOGGED_VALIDATION_ERRORS = 20
_SAFE_CONTRACT_FIELD_IDENTIFIERS = frozenset(
    {
        "source",
        "eligibility_criteria",
        "sample_size_or_power_basis",
        "symbol_references",
        "variable_references",
    }
)
_SAFE_FIELD_STATUS_PATH = re.compile(
    r"^(?:research_design|hypothesis_mapping|variables_and_operationalization|"
    r"sampling_and_eligibility|measurement_and_calibration|"
    r"comparison_and_robustness|analysis_plan|"
    r"data_governance_and_reproducibility|template_details)"
    r"(?:\.[A-Za-z][A-Za-z0-9_]{0,63}|\[\d+\])*$"
)
_SAFE_UNEXPECTED_PROPERTY_NAME = re.compile(r"'([A-Za-z][A-Za-z0-9_]{0,63})'")
_SENSITIVE_UNEXPECTED_PROPERTY_NAME = re.compile(
    r"api_?key|authorization|credential|pass(?:word)?|secret|token|patient|email|phone|ssn",
    re.IGNORECASE,
)
_UNEXPECTED_PROPERTY_NAMES = re.compile(
    r"Additional properties are not allowed \((?P<names>.+?) (?:was|were) unexpected\)"
)


class RequiredJsonLLMError(RuntimeError):
    """Raised when a required LLM stage cannot produce one JSON object."""


def response_summary(raw: object) -> dict[str, object]:
    """Return format diagnostics without retaining model-generated content."""

    if isinstance(raw, str):
        stripped = raw.lstrip()
        return {
            "response_type": "str",
            "response_character_count": len(raw),
            "response_starts_with_json_object": stripped.startswith("{"),
            "response_has_code_fence": stripped.startswith("```"),
        }
    if isinstance(raw, Mapping):
        return {
            "response_type": type(raw).__name__,
            "response_top_level_key_count": len(raw),
        }
    return {"response_type": type(raw).__name__}


def validation_summary(errors: list[str]) -> dict[str, object]:
    """Bound deterministic validation diagnostics for run logs."""

    return {
        "validation_error_count": len(errors),
        "validation_errors": [
            _safe_validation_error_identifier(error)
            for error in errors[:MAX_LOGGED_VALIDATION_ERRORS]
        ],
        "validation_errors_truncated": len(errors) > MAX_LOGGED_VALIDATION_ERRORS,
    }


def _safe_unexpected_property_names(message: str) -> tuple[str, ...]:
    """Return log-safe schema key names from an additional-properties error."""

    match = _UNEXPECTED_PROPERTY_NAMES.search(message)
    if match is None:
        return ()
    names: list[str] = []
    for name in _SAFE_UNEXPECTED_PROPERTY_NAME.findall(match.group("names")):
        if (
            _SENSITIVE_UNEXPECTED_PROPERTY_NAME.search(name)
            or name in names
        ):
            continue
        names.append(name)
    return tuple(names)


def _safe_validation_error_identifier(error: object) -> str:
    """Keep deterministic error codes while excluding untrusted field values."""

    text = str(error or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", text):
        prefix, _, suffix = text.partition(":")
        if not suffix:
            return text[:500]
        if (
            prefix == "formal_theory_sampling_must_be_not_applicable"
            and suffix in _SAFE_CONTRACT_FIELD_IDENTIFIERS
        ):
            return text[:500]
        if suffix in _SAFE_CONTRACT_FIELD_IDENTIFIERS:
            return text[:500]
        if (
            prefix == "field_status_evidence_not_qualified"
            and _SAFE_FIELD_STATUS_PATH.fullmatch(suffix)
            and not _SENSITIVE_UNEXPECTED_PROPERTY_NAME.search(suffix)
        ):
            return text[:500]
        return prefix[:500]
    path_match = re.search(r"\$(?:/[A-Za-z0-9_.\[\]-]+)*", text)
    if path_match:
        message = text[path_match.end():]
        error_type = "schema_validation_error"
        if "is not of type" in message:
            error_type = "type_mismatch"
        elif "is a required property" in message:
            error_type = "required_property_missing"
        elif "Additional properties are not allowed" in message:
            error_type = "additional_property"
            names = _safe_unexpected_property_names(message)
            if names:
                return (
                    f"{path_match.group(0)}:{error_type}:"
                    f"safe_unexpected_keys={','.join(names)}"
                )[:500]
        elif "is not one of" in message:
            error_type = "enum_mismatch"
        elif "is too short" in message or "is too long" in message:
            error_type = "length_violation"
        elif "is not valid under any of the given schemas" in message:
            error_type = "schema_variant_mismatch"
        return f"{path_match.group(0)}:{error_type}"[:500]
    prefix = text.split(":", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", prefix):
        return prefix[:500]
    return "schema_or_contract_validation_error"


def call_required_json(
    llm_call: Callable[..., object] | None,
    prompt: str,
    *,
    stage: str,
) -> dict[str, Any]:
    """Invoke a required stage with JSON-object mode and reject every fallback."""

    if llm_call is None:
        raise RequiredJsonLLMError(f"{stage}: an LLM callback is required; no fallback is permitted")
    try:
        raw = llm_call(prompt, response_format=JSON_OBJECT_RESPONSE_FORMAT)
    except Exception as exc:
        raise RequiredJsonLLMError(f"{stage}: LLM invocation failed: {type(exc).__name__}: {exc}") from exc
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        raise RequiredJsonLLMError(
            f"{stage}: LLM callback returned {type(raw).__name__}; expected a JSON object or JSON text"
        )
    try:
        return parse_json_object_response(raw)
    except JsonObjectResponseError as exc:
        raise RequiredJsonLLMError(f"{stage}: LLM response was not one complete JSON object") from exc


def call_required_json_with_logging(
    llm_call: Callable[..., object] | None,
    prompt: str,
    *,
    stage: str,
    request_kind: str,
    logger: Any | None,
    brief_id: str,
) -> dict[str, Any]:
    """Invoke one strict JSON request and emit only safe transport metadata."""

    started_at = perf_counter()
    if logger is not None:
        logger.event(
            stage,
            "llm_request_started",
            status="RUNNING",
            brief_id=brief_id,
            request_kind=request_kind,
            response_format="json_object",
        )

    def observed_llm_call(inner_prompt: str, **kwargs: object) -> object:
        try:
            raw = llm_call(inner_prompt, **kwargs) if llm_call is not None else None
        except Exception as exc:
            if logger is not None:
                logger.exception(
                    stage,
                    exc,
                    event="llm_request_failed",
                    status="FAILED",
                    elapsed_ms=(perf_counter() - started_at) * 1000,
                    brief_id=brief_id,
                    request_kind=request_kind,
                )
            raise
        if logger is not None:
            logger.event(
                stage,
                "llm_response_received",
                status="RECEIVED",
                elapsed_ms=(perf_counter() - started_at) * 1000,
                brief_id=brief_id,
                request_kind=request_kind,
                **response_summary(raw),
            )
        return raw

    try:
        payload = call_required_json(
            observed_llm_call if llm_call is not None else None,
            prompt,
            stage=stage,
        )
    except Exception as exc:
        if logger is not None:
            logger.exception(
                stage,
                exc,
                event="llm_json_contract_failed",
                status="FAILED",
                elapsed_ms=(perf_counter() - started_at) * 1000,
                brief_id=brief_id,
                request_kind=request_kind,
            )
        raise
    if logger is not None:
        logger.event(
            stage,
            "llm_json_parsed",
            status="PARSED",
            elapsed_ms=(perf_counter() - started_at) * 1000,
            brief_id=brief_id,
            request_kind=request_kind,
            response_top_level_key_count=len(payload),
            schema_version=str(payload.get("schema_version") or ""),
        )
    return payload


def json_prompt_payload(value: Mapping[str, Any]) -> str:
    """Serialize an untrusted input payload deterministically for a JSON prompt."""

    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def build_default_json_llm_call(
    *,
    config: Any = None,
    model: Optional[str] = None,
) -> Callable[..., object]:
    """Build the project's configured LLM callback lazily.

    The callback is deliberately constructed on first invocation rather than at
    agent import or construction time.  This keeps configuration and client
    errors attached to the required LLM stage that caused them, while still
    making a normal ExperimentDesign run use the real configured provider by
    default.  ``call_required_json`` remains the single enforcement point for
    JSON-object mode and explicit failure.
    """

    holder: dict[str, Any] = {}

    def setting(value: Any, key: str, default: Any = "") -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    def experiment_design_setting(key: str, default: Any = "") -> Any:
        runtime_config = config
        if runtime_config is None:
            from src.config import get_config

            runtime_config = get_config()
        return setting(setting(runtime_config, "experiment_design", {}), key, default)

    def _call(prompt: str, **kwargs: Any) -> object:
        if "response_format" not in kwargs:
            kwargs["response_format"] = JSON_OBJECT_RESPONSE_FORMAT
        if kwargs["response_format"] != JSON_OBJECT_RESPONSE_FORMAT:
            raise RequiredJsonLLMError(
                "experiment_design: the default callback only supports JSON object response format"
            )
        resolved_model = str(model or "").strip()
        if not resolved_model:
            resolved_model = str(experiment_design_setting("model") or "").strip()
        runtime_config = config
        if runtime_config is None:
            from src.config import get_config

            runtime_config = get_config()
        provider_name = str(experiment_design_setting("provider") or "").strip()
        if str(model or "").strip():
            provider_name = resolve_model(runtime_config, resolved_model).provider
        agent = holder.get("agent")
        if agent is None:
            from src.agents.idea_agent.agent.base import AgentBase

            agent = AgentBase(config=runtime_config, provider_name=provider_name or None)
            holder["agent"] = agent
        if not resolved_model:
            resolved_model = str(agent.provider.default_models.get("experiment_design") or "").strip()
        if not resolved_model:
            resolved_model = str(agent.provider.default_models.get("experiment") or "").strip()
        if not resolved_model:
            raise RequiredJsonLLMError(
                "experiment_design: no model is configured for the experiment-design LLM role"
            )
        return agent.chat(prompt, model=resolved_model, **kwargs)

    return _call
