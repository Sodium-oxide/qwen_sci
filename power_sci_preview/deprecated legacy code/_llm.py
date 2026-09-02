from __future__ import annotations

from datetime import date, timedelta
from typing import Any
import ast
import json
import re
import time

try:
    from .config import (
        QWEN_API_BASE,
        QWEN_API_KEY,
        QWEN_MODEL_ID,
        SCIENCE_LLM_EXTRACTOR,
    )
    from .log import log_event
except ImportError:
    from config import (
        QWEN_API_BASE,
        QWEN_API_KEY,
        QWEN_MODEL_ID,
        SCIENCE_LLM_EXTRACTOR,
    )
    from log import log_event


class LLMJSONProtocolError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "LLM_JSON_PROTOCOL_INVALID")
        self.diagnostics = dict(diagnostics or {})


class LLMTransportError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


def _bounded_error_text(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _response_preview(value: Any, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]} … {text[-tail:]}"


def _provider_diagnostics(value: Any) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "error_type": type(value).__name__,
        "error_message": _bounded_error_text(value),
    }
    nested = getattr(value, "diagnostics", None)
    if isinstance(nested, dict):
        diagnostics.update({
            key: nested.get(key)
            for key in ("provider_code", "request_id", "status_code")
            if nested.get(key) not in (None, "")
        })
    for field in ("provider_code", "code", "request_id", "status_code"):
        field_value = getattr(value, field, None)
        if field_value not in (None, "") and field not in diagnostics:
            diagnostics[field if field != "code" else "provider_code"] = str(field_value)
    message = diagnostics["error_message"]
    for field, pattern in (
        ("status_code", r"status_code=([^,\s]+)"),
        ("provider_code", r"(?:^|[\s,])(?:provider_code|code)=([^,\s]+)"),
        ("request_id", r"request_id=([^,\s]+)"),
    ):
        if not diagnostics.get(field):
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                diagnostics[field] = match.group(1)
    return diagnostics


def _response_metadata(response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field, output_name in (
        ("status_code", "status_code"),
        ("code", "provider_code"),
        ("provider_code", "provider_code"),
        ("request_id", "request_id"),
    ):
        value = getattr(response, field, None)
        if isinstance(response, dict):
            value = response.get(field, value)
        if value not in (None, ""):
            metadata[output_name] = str(value)
    return metadata


def _llm_response_finish_reason(response: Any) -> str:
    for field in ("stop_reason", "finish_reason", "stopReason", "finishReason"):
        value = getattr(response, field, None)
        if value:
            return str(value)
        if isinstance(response, dict) and response.get(field):
            return str(response[field])
    output = getattr(response, "output", None)
    if isinstance(response, dict):
        output = response.get("output", output)
    if isinstance(output, dict):
        for field in ("stop_reason", "finish_reason"):
            if output.get(field):
                return str(output[field])
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    for field in ("finish_reason", "stop_reason"):
                        if choice.get(field):
                            return str(choice[field])
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    for field in ("finish_reason", "stop_reason"):
                        if choice.get(field):
                            return str(choice[field])
    return ""


def _invoke_llm_text(
    *,
    system: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    try:
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _science_execution_policy import resolve_science_execution_policy
    policy = resolve_science_execution_policy({})
    try:
        client = get_science_llm_client()
    except Exception as exc:
        diagnostics = _provider_diagnostics(exc)
        raise LLMTransportError(diagnostics["error_message"], diagnostics) from exc
    response = None
    for attempt in range(policy.max_transport_retries + 1):
        try:
            response = client.messages.create(
                model=None,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                request_timeout=(
                    policy.connect_timeout_seconds,
                    policy.total_timeout_seconds,
                ),
            )
            break
        except Exception as exc:
            error_text = str(exc).casefold()
            retryable = any(marker in error_text for marker in (
                "timeout", "timed out", "rate limit", "too many requests",
                "connection", "temporarily unavailable", "service unavailable",
            ))
            if not retryable or attempt >= policy.max_transport_retries:
                diagnostics = _provider_diagnostics(exc)
                raise LLMTransportError(diagnostics["error_message"], diagnostics) from exc
            log_event(
                "WARN",
                "llm_transport_retry",
                attempt=attempt + 1,
                max_transport_retries=policy.max_transport_retries,
                total_timeout_seconds=policy.total_timeout_seconds,
                error_type=type(exc).__name__,
            )
    if response is None:
        diagnostics = {
            "error_type": "RuntimeError",
            "error_message": "LLM request completed without a response",
        }
        raise LLMTransportError(diagnostics["error_message"], diagnostics)
    rendered = render_llm_response_text(getattr(response, "content", response))
    return rendered, {
        "response_chars": len(rendered),
        "finish_reason": _llm_response_finish_reason(response),
        "max_tokens": int(max_tokens),
        **_response_metadata(response),
    }



def parse_jsonish_dict(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"text": value}
    return {}

def call_llm_json(
    system: str,
    prompt: str,
    max_tokens: int = 2000,
    fallback_list_key: str = "",
) -> dict[str, Any]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    rendered, _ = _invoke_llm_text(
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
    )
    parsed, _ = parse_json_object_from_text_with_diagnostics(
        rendered,
        fallback_list_key=fallback_list_key,
    )
    if not parsed:
        log_event(
            "WARN",
            "llm_json_parse_failed",
            chars=len(rendered),
            snippet=trim_text(rendered, 500),
        )
        raise ValueError("LLM did not return a JSON object")
    return parsed


def call_llm_json_contract(
    *,
    system: str,
    prompt: str,
    max_tokens: int,
    required_list_key: str,
    protocol_name: str,
    allow_empty: bool = False,
    expected_schema_version: str = "",
    required_root_list_keys: tuple[str, ...] = (),
    allow_partial_recovery: bool = True,
) -> dict[str, Any]:
    """Call the LLM and enforce one explicit root list contract."""

    rendered, response_diagnostics = _invoke_llm_text(
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
    )
    parsed, parse_diagnostics = parse_json_object_from_text_with_diagnostics(
        rendered,
        fallback_list_key=required_list_key if allow_partial_recovery else "",
    )
    diagnostics = {
        **response_diagnostics,
        **parse_diagnostics,
        "required_list_key": required_list_key,
        "top_level_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else [],
    }
    finish_reason = str(diagnostics.get("finish_reason") or "").casefold()
    diagnostics["response_truncated"] = bool(
        diagnostics.get("recovery_mode") == "keyed_partial_array"
        or diagnostics.get("root_object_unbalanced") is True
        or "length" in finish_reason
        or "max_token" in finish_reason
    )
    code_prefix = str(protocol_name or "LLM_JSON").strip().upper()
    if diagnostics["response_truncated"]:
        diagnostics["response_preview"] = _response_preview(rendered)
        if not allow_partial_recovery:
            partial_payload, partial_diagnostics = parse_json_object_from_text_with_diagnostics(
                rendered,
                fallback_list_key=required_list_key,
            )
            if (
                isinstance(partial_payload, dict)
                and isinstance(partial_payload.get(required_list_key), list)
                and partial_diagnostics.get("recovery_mode") == "keyed_partial_array"
            ):
                diagnostics["safe_partial_payload"] = partial_payload
                diagnostics["safe_partial_recovery"] = True
                diagnostics["top_level_keys"] = [required_list_key]
        raise LLMJSONProtocolError(
            f"{code_prefix}_RESPONSE_TRUNCATED",
            f"{protocol_name} response was truncated before the root contract completed",
            diagnostics,
        )
    if not parsed:
        diagnostics["response_preview"] = _response_preview(rendered)
        raise LLMJSONProtocolError(
            f"{code_prefix}_ROOT_PROTOCOL_INVALID",
            f"{protocol_name} did not return a JSON object",
            diagnostics,
        )
    if diagnostics.get("wrapped_top_level_list") is True:
        diagnostics["response_preview"] = _response_preview(rendered)
        raise LLMJSONProtocolError(
            f"{code_prefix}_ROOT_PROTOCOL_INVALID",
            f"{protocol_name} requires a root JSON object, not a top-level array",
            diagnostics,
        )
    if expected_schema_version and str(parsed.get("schema_version") or "") != expected_schema_version:
        diagnostics["response_preview"] = _response_preview(rendered)
        diagnostics["expected_schema_version"] = expected_schema_version
        diagnostics["actual_schema_version"] = str(parsed.get("schema_version") or "")
        raise LLMJSONProtocolError(
            f"{code_prefix}_ROOT_PROTOCOL_INVALID",
            f"{protocol_name} requires schema_version={expected_schema_version}",
            diagnostics,
        )
    if required_list_key not in parsed or not isinstance(parsed.get(required_list_key), list):
        diagnostics["response_preview"] = _response_preview(rendered)
        raise LLMJSONProtocolError(
            f"{code_prefix}_ROOT_PROTOCOL_INVALID",
            f"{protocol_name} requires a root {required_list_key} array",
            diagnostics,
        )
    invalid_root_lists = [
        key
        for key in required_root_list_keys
        if key not in parsed or not isinstance(parsed.get(key), list)
    ]
    if invalid_root_lists:
        diagnostics["response_preview"] = _response_preview(rendered)
        diagnostics["invalid_root_list_keys"] = invalid_root_lists
        raise LLMJSONProtocolError(
            f"{code_prefix}_ROOT_PROTOCOL_INVALID",
            f"{protocol_name} requires root arrays: {', '.join(invalid_root_lists)}",
            diagnostics,
        )
    if not allow_empty and not parsed[required_list_key]:
        diagnostics["response_preview"] = _response_preview(rendered)
        raise LLMJSONProtocolError(
            f"{code_prefix}_EMPTY",
            f"{protocol_name} returned an empty {required_list_key} array",
            diagnostics,
        )
    return {"payload": parsed, "diagnostics": diagnostics}


def translate_scientific_query_to_english(query: str, domain: str = "") -> str:
    source = str(query or "").strip()
    if not source:
        return ""
    payload = call_llm_json(
        system=(
            "You translate scientific literature search queries. Return only JSON and never add scientific claims, "
            "papers, measurements, or constraints that are absent from the source."
        ),
        prompt=(
            "Convert this query into 4-12 concise English academic retrieval keywords or phrases. "
            "The value must contain English letters only for concepts; keep standard chemical, gene, and protein symbols when present. "
            "Do not output Chinese, explanations, Boolean syntax, or a sentence.\n\n"
            f"Domain context: {str(domain or '')[:400]}\n"
            f"Source query: {source[:800]}\n\n"
            'Return exactly: {"query":"english retrieval keywords"}'
        ),
        max_tokens=260,
    )
    candidate = str(payload.get("query") or "").strip()
    if not candidate or re.search(r"[\u3400-\u9fff\uf900-\ufaff]", candidate):
        return ""
    return re.sub(r"\s+", " ", candidate)


_PUBLIC_FRAMING_MARKERS = (
    "how can we",
    "how to",
    "better manage",
    "improve",
    "address this issue",
    "solve",
    "tackle",
    "reduce pollution",
    "save the planet",
    "sustainable future",
    "environmentally advantageous",
    "economically feasible",
    "useful for such efforts",
)

_SOLUTION_LIST_MARKERS = (
    "recycling",
    "recycle",
    "ban",
    "banning",
    "incineration",
    "waste-to-energy",
    "waste to energy",
    "fuel",
    "material flow analysis",
    "publicly available data",
    "policy",
    "reuse",
    "reduce",
    "alternative uses",
    "strategies",
)

_COMPARISON_MARKERS = (
    "compared with",
    "compared to",
    "versus",
    " vs ",
    "baseline",
    "counterfactual",
    "control group",
    "control condition",
    "matched control",
    "controlled",
    "reference condition",
    "relative to",
)

_BOUNDARY_MARKERS = (
    "under",
    "when",
    "where",
    "context",
    "boundary",
    "condition",
    "regional",
    "population",
    "in ",
    "across",
    "within",
)

_ADVERSE_MARKERS = (
    "adverse",
    "negative",
    "rebound",
    "substitution",
    "burden shifting",
    "burden-shifting",
    "trade-off",
    "tradeoff",
    "unintended consequence",
    "failure",
    "resource competition",
    "competing",
    "worse",
)

_FALSIFICATION_MARKERS = (
    "falsif",
    "refute",
    "weakened if",
    "fails if",
    "does not",
    "no significant",
    "null effect",
    "ineffective",
    "threshold",
)

_REVIEW_OR_FIELD_INTRO_MARKERS = (
    "to understand how",
    "understand how",
    "how are ",
    "how is ",
    "what is the role",
    "role of ",
    "importance of ",
    "well known",
    "it is well known",
    "recent findings",
    "recent advances",
    "booming development",
    "continues to provide",
    "valuable mechanistic perspectives",
    "uncovered another important level",
    "scientists are using",
    "researchers note",
    "provide valuable",
)

_MEASURABLE_ENDPOINT_MARKERS = (
    "endpoint",
    "readout",
    "assay",
    "rate",
    "ratio",
    "fraction",
    "index",
    "score",
    "coefficient",
    "concentration",
    "abundance",
    "activity",
    "flux",
    "yield",
    "potency",
    "purity",
    "sterility",
    "accuracy",
    "error",
    "auc",
    "cmax",
    "ic50",
    "ec50",
    "half-life",
    "half time",
    "half-time",
    "survival",
    "mortality",
    "toxicity",
    "expression",
    "localization",
    "localisation",
    "resolution",
    "signal-to-noise",
    "sensitivity",
    "specificity",
    "calibration",
    "emission",
    "leakage",
    "carbon footprint",
    "cost",
    "turnaround time",
    "failure rate",
    "degradation rate",
    "conductivity",
    "strength",
    "stiffness",
    "viscosity",
    "elasticity",
    "transport rate",
)

_VARIABLE_RESOLUTION_MARKERS = (
    "dose",
    "ratio",
    "fraction",
    "concentration",
    "content",
    "rate",
    "threshold",
    "gradient",
    "temperature",
    "pressure",
    "time",
    "duration",
    "frequency",
    "intensity",
    "density",
    "size",
    "length",
    "charge",
    "ph",
    "mutation",
    "genotype",
    "allele",
    "knockout",
    "inhibition",
    "ablation",
    "overexpression",
    "deletion",
    "addition",
    "removal",
    "substitution",
    "replacement",
    "feature set",
    "architecture",
    "calibration",
    "external validation",
    "distribution shift",
)

_LOW_RESOLUTION_VARIABLE_MARKERS = (
    "composition",
    "condition",
    "conditions",
    "organization",
    "organisation",
    "structure",
    "design",
    "strategy",
    "approach",
    "management",
    "process",
    "workflow",
    "platform",
    "environment",
    "treatment history",
    "model design",
    "data quality",
)

_NATURAL_SCIENCE_OPERATIONALIZATION_FIELDS = (
    "agricultural and biological sciences",
    "biochemistry, genetics and molecular biology",
    "chemical engineering",
    "chemistry",
    "computer science",
    "earth and planetary sciences",
    "energy",
    "engineering",
    "environmental science",
    "immunology and microbiology",
    "materials science",
    "mathematics",
    "medicine",
    "neuroscience",
    "nursing",
    "pharmacology, toxicology and pharmaceutics",
    "physics and astronomy",
    "veterinary",
    "dentistry",
    "health professions",
)


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = f" {str(text or '').lower()} "
    return any(marker in lowered for marker in markers)


def _contains_term_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(marker.strip().lower())}(?![a-z0-9])", lowered)
        for marker in markers
        if str(marker or "").strip()
    )


def _public_framing_action(failure_count: int) -> str:
    if failure_count > 3:
        return "academic_reframing_required"
    if failure_count > 0:
        return "targeted_refinement_suggested"
    return "rigorous_enough"


def _audit_action_for_payload(normalized: dict[str, Any], failure_count: int) -> str:
    if normalized.get("is_under_operationalized_academic_framing") and (
        normalized.get("missing_measurable_endpoint")
        or normalized.get("missing_variable_resolution")
        or normalized.get("missing_comparison")
        or normalized.get("missing_falsification")
    ):
        return "academic_operationalization"
    return _public_framing_action(failure_count)


def _normalize_public_framing_audit(
    payload: dict[str, Any],
    *,
    original_text: str,
    extractor: str,
) -> dict[str, Any]:
    bool_keys = (
        "is_public_framing",
        "is_solution_list_like",
        "is_review_or_field_intro_like",
        "is_under_operationalized_academic_framing",
        "missing_mechanism",
        "missing_comparison",
        "missing_boundary_conditions",
        "missing_adverse_or_reversal_path",
        "missing_falsification",
        "missing_measurable_endpoint",
        "missing_variable_resolution",
    )
    normalized: dict[str, Any] = {
        key: bool(payload.get(key))
        for key in bool_keys
    }
    failure_count = sum(1 for key in bool_keys if normalized[key])
    try:
        supplied_count = int(payload.get("failure_count"))
        if 0 <= supplied_count <= len(bool_keys):
            failure_count = supplied_count
    except (TypeError, ValueError):
        pass
    action = str(payload.get("recommended_action") or "").strip().lower()
    action = action.replace("-", "_").replace(" ", "_")
    if action in {"academic_reframing", "reframing_required", "major_rewrite"}:
        action = "academic_reframing_required"
    elif action in {"academic_operationalization", "operationalization_required", "academic_operationalisation"}:
        action = "academic_operationalization"
    elif action not in {
        "academic_reframing_required",
        "academic_operationalization",
        "targeted_refinement_suggested",
        "rigorous_enough",
    }:
        action = _audit_action_for_payload(normalized, failure_count)
    if (
        action == "academic_reframing_required"
        and not normalized.get("is_public_framing")
        and not normalized.get("is_solution_list_like")
        and (
            normalized.get("is_under_operationalized_academic_framing")
            or normalized.get("is_review_or_field_intro_like")
        )
        and (
            normalized.get("missing_measurable_endpoint")
            or normalized.get("missing_variable_resolution")
            or normalized.get("missing_comparison")
            or normalized.get("missing_falsification")
        )
    ):
        action = "academic_operationalization"
    suggestions = payload.get("reframing_suggestions")
    suggestions = suggestions if isinstance(suggestions, list) else []
    detected_weaknesses = [
        label
        for key, label in (
            ("is_public_framing", "public-facing or slogan-like framing"),
            ("is_solution_list_like", "solution-list-like framing"),
            ("is_review_or_field_intro_like", "academic review-introduction framing"),
            ("is_under_operationalized_academic_framing", "academic but under-operationalized framing"),
            ("missing_mechanism", "no explicit mechanism"),
            ("missing_comparison", "no baseline or counterfactual"),
            ("missing_boundary_conditions", "no boundary condition"),
            ("missing_adverse_or_reversal_path", "no adverse or reversal path"),
            ("missing_falsification", "no falsification condition"),
            ("missing_measurable_endpoint", "no concrete measurable endpoint"),
            ("missing_variable_resolution", "input variable lacks parameter-level resolution"),
        )
        if normalized.get(key)
    ]
    normalized.update(
        {
            "schema_version": "scientific_framing_audit_v2",
            "failure_count": failure_count,
            "recommended_action": action,
            "detected_weaknesses": detected_weaknesses,
            "reframing_suggestions": [str(item)[:500] for item in suggestions[:8] if str(item).strip()],
            "brief_rationale": str(payload.get("brief_rationale") or "")[:900],
            "original_text_sample": str(original_text or "")[:1200],
            "extractor": extractor,
        }
    )
    if not normalized["brief_rationale"]:
        normalized["brief_rationale"] = (
            "The objective lacks enough comparative, mechanistic, boundary, adverse-path, "
            "or falsification structure for direct sub-hypothesis decomposition."
            if failure_count
            else "The objective contains enough scientific structure for direct decomposition."
        )
    return normalized


def _heuristic_public_framing_audit(project_objective: str, domain: str = "", research_brief: str = "") -> dict[str, Any]:
    text = " ".join(part for part in (domain, project_objective, research_brief) if str(part or "").strip())
    lowered = text.lower()
    solution_hits = sum(1 for marker in _SOLUTION_LIST_MARKERS if marker in lowered)
    public_like = _contains_any_marker(lowered, _PUBLIC_FRAMING_MARKERS)
    enumerative_list = bool(re.search(r"\b(?:including|such as)\b.+(?:,| and | or ).+", lowered))
    list_like = solution_hits >= 2 or bool((public_like or solution_hits >= 1) and enumerative_list)
    has_mechanism = any(marker in lowered for marker in ("mechanism", "mechanistic", "pathway", "mediates", "via ", "through ", "causal", "process-level", "process level"))
    has_endpoint = _contains_term_marker(lowered, _MEASURABLE_ENDPOINT_MARKERS)
    has_variable_resolution = _contains_term_marker(lowered, _VARIABLE_RESOLUTION_MARKERS)
    low_resolution_variable_language = _contains_any_marker(lowered, _LOW_RESOLUTION_VARIABLE_MARKERS)
    review_intro_like = _contains_any_marker(lowered, _REVIEW_OR_FIELD_INTRO_MARKERS)
    under_operationalized_academic = bool(
        review_intro_like
        and not public_like
        and not list_like
        and (not has_endpoint or not has_variable_resolution or not _contains_any_marker(lowered, _COMPARISON_MARKERS))
    )
    payload = {
        "is_public_framing": public_like,
        "is_solution_list_like": list_like,
        "is_review_or_field_intro_like": review_intro_like,
        "is_under_operationalized_academic_framing": under_operationalized_academic,
        "missing_mechanism": not has_mechanism,
        "missing_comparison": not _contains_any_marker(lowered, _COMPARISON_MARKERS),
        "missing_boundary_conditions": (
            ("world" in lowered or "global" in lowered or "universal" in lowered)
            and not any(marker in lowered for marker in ("under ", "when ", "boundary", "constraint", "heterogeneity"))
        ),
        "missing_adverse_or_reversal_path": not _contains_any_marker(lowered, _ADVERSE_MARKERS),
        "missing_falsification": not _contains_any_marker(lowered, _FALSIFICATION_MARKERS),
        "missing_measurable_endpoint": not has_endpoint,
        "missing_variable_resolution": bool(
            (review_intro_like or low_resolution_variable_language)
            and not has_variable_resolution
        ),
        "reframing_suggestions": [
            "Add an explicit baseline or counterfactual instead of listing attractive strategies.",
            "Add an adverse or reversal path such as rebound, burden shifting, resource competition, or implementation failure.",
            "State the boundary conditions under which the proposed strategy should or should not work.",
            "Name the measurable endpoint and the condition that would falsify the proposed mechanism.",
            "For academic review-introduction inputs, convert broad objects or mechanisms into parameterized variables, explicit comparisons, and concrete assay/statistic/readout endpoints.",
        ],
        "brief_rationale": (
            "Heuristic audit: the text reads as a broad problem, solution list, or academic field-introduction "
            "unless it declares mechanism, parameter-level variables, concrete endpoints, comparator, boundary, "
            "adverse path, and falsification."
        ),
    }
    if has_endpoint and not public_like and not list_like:
        payload["is_public_framing"] = False
    return _normalize_public_framing_audit(payload, original_text=text, extractor="heuristic")


def detect_public_or_solution_list_framing(
    project_objective: str,
    *,
    domain: str = "",
    research_brief: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Audit whether a project brief is too public-facing for direct SH decomposition."""

    objective = str(project_objective or "").strip()
    brief = str(research_brief or "").strip()
    domain_text = str(domain or "").strip()
    if not objective and not brief:
        return _normalize_public_framing_audit(
            {
                "is_public_framing": True,
                "is_solution_list_like": False,
                "is_review_or_field_intro_like": False,
                "is_under_operationalized_academic_framing": False,
                "missing_mechanism": True,
                "missing_comparison": True,
                "missing_boundary_conditions": True,
                "missing_adverse_or_reversal_path": True,
                "missing_falsification": True,
                "missing_measurable_endpoint": True,
                "missing_variable_resolution": True,
                "reframing_suggestions": ["Provide a concrete research objective before decomposition."],
                "brief_rationale": "No objective text was supplied.",
            },
            original_text="",
            extractor="deterministic_empty_input",
        )
    if use_llm:
        prompt_payload = {
            "project_objective": objective,
            "domain": domain_text,
            "research_brief": brief[:6000],
        }
        try:
            payload = call_llm_json(
                system=(
                    "You are the Scientific Hypothesis Gatekeeper, an expert in research methodology "
                    "and philosophy of science. Audit research objectives for academic rigor. A valid "
                    "scientific question should be falsifiable, comparative, and mechanistic; it must not "
                    "be merely a public slogan, policy advocacy statement, list of familiar solutions, "
                    "or academic review-introduction that has not been operationalized into variables, "
                    "comparators, endpoints, and falsification. Apply this across natural sciences, "
                    f"engineering, health, environmental, materials, mathematical, and computational fields "
                    f"such as: {', '.join(_NATURAL_SCIENCE_OPERATIONALIZATION_FIELDS)}. Do not use humanities "
                    "or social-science-only standards as the default for this audit. "
                    "Return JSON only."
                ),
                prompt=(
                    "Audit the input against exactly these dimensions: public framing; solution listing; "
                    "academic review-introduction framing; academic but under-operationalized framing; "
                    "missing mechanism; missing comparison/baseline/counterfactual; missing boundary "
                    "conditions; missing adverse/reversal path; missing falsification; missing concrete "
                    "measurable endpoint; missing variable resolution. A text fails when it lists multiple "
                    "strategies without prioritization or comparison, assumes all strategies are beneficial, "
                    "lacks a baseline, lacks adverse/reversal mechanisms, lacks boundary conditions, lacks "
                    "falsification, lacks concrete measurable endpoints, or describes broad composition, "
                    "conditions, organization, strategy, model design, process, or treatment history without "
                    "parameter-level resolution. Academic review-introduction phrases such as 'to understand "
                    "how', 'role of', 'well known', 'recent findings', 'booming development', or 'valuable "
                    "mechanistic perspectives' are not non-academic, but they require academic_operationalization "
                    "when they lack variables, endpoints, comparison, or falsification.\n\n"
                    f"INPUT_JSON:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}\n\n"
                    "Return exactly one JSON object with keys: is_public_framing, is_solution_list_like, "
                    "is_review_or_field_intro_like, is_under_operationalized_academic_framing, "
                    "missing_mechanism, missing_comparison, missing_boundary_conditions, "
                    "missing_adverse_or_reversal_path, missing_falsification, missing_measurable_endpoint, "
                    "missing_variable_resolution, failure_count, "
                    "recommended_action, reframing_suggestions, brief_rationale. recommended_action must "
                    "be academic_reframing_required when a public/solution-list objective needs rewriting, "
                    "academic_operationalization when an academic review-introduction needs variable/readout "
                    "resolution before SH decomposition, "
                    "targeted_refinement_suggested when 1-2 fail, or rigorous_enough when none fail."
                ),
                max_tokens=900,
            )
            return _normalize_public_framing_audit(
                payload,
                original_text=" ".join(part for part in (domain_text, objective, brief) if part),
                extractor="llm",
            )
        except Exception as exc:
            fallback = _heuristic_public_framing_audit(objective, domain_text, brief)
            fallback["llm_error"] = str(exc)[:300]
            fallback["extractor"] = "heuristic_after_llm_failure"
            return fallback
    return _heuristic_public_framing_audit(objective, domain_text, brief)


_ACADEMIC_REFRAMING_SUBJECT_STOPWORDS = frozenset({
    "about", "above", "across", "after", "against", "also", "among", "because",
    "better", "could", "data", "does", "from", "gathering", "global", "have",
    "including", "into", "lack", "manage", "more", "need", "needs",
    "potential", "products", "publicly", "recently", "reliable", "research",
    "researchers", "should", "solutions", "study", "that", "their", "there",
    "these", "this", "through", "using", "what", "when", "where",
    "which", "while", "world", "worlds",
})


def _domain_general_reframing_subject(
    *,
    original_objective: str,
    domain: str = "",
    research_brief: str = "",
) -> str:
    """Derive a scoped subject phrase without using discipline-specific patches."""

    domain_text = re.sub(r"\s+", " ", str(domain or "").strip())
    if domain_text:
        return domain_text[:120]
    text = f"{original_objective} {research_brief}".lower()
    words = [
        word
        for word in re.findall(r"[a-z][a-z0-9-]{2,}", text)
        if word not in _ACADEMIC_REFRAMING_SUBJECT_STOPWORDS
    ]
    if not words:
        return "candidate"
    counts: dict[str, int] = {}
    ordered: list[str] = []
    for word in words:
        counts[word] = counts.get(word, 0) + 1
        if word not in ordered:
            ordered.append(word)
    ranked = sorted(ordered, key=lambda item: (-counts[item], ordered.index(item)))
    subject_terms = ranked[:4]
    if len(subject_terms) >= 2:
        return " ".join(subject_terms)[:120]
    return subject_terms[0][:120]


def _domain_general_academic_reframing(
    original_objective: str,
    *,
    domain: str = "",
    research_brief: str = "",
    reframing_type: str = "academic_reframing_required",
) -> dict[str, Any]:
    subject = _domain_general_reframing_subject(
        original_objective=original_objective,
        domain=domain,
        research_brief=research_brief,
    )
    normalized_type = str(reframing_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_type in {"academic_operationalisation", "operationalization_required"}:
        normalized_type = "academic_operationalization"
    if normalized_type == "academic_operationalization":
        return {
            "academic_objective": (
                f"Which parameterized changes in {subject} organization, composition, conditions, "
                "measurement systems, models, or processes alter concrete mechanism-linked readouts "
                "compared with explicit baselines, under which boundary conditions, and which null, "
                "alternative, adverse, or reversal mechanisms would weaken the proposed relation?"
            ),
            "reframing_type": "academic_operationalization",
            "reframing_axes": [
                "parameter-level variable resolution",
                "concrete measurable endpoint definition",
                "explicit baseline or counterfactual comparison",
                "mechanism-linked readout selection",
                "boundary or moderator definition",
                "null, alternative, adverse, or reversal mechanism pressure",
            ],
            "baseline_requirements": [
                "matched control or reference condition",
                "parameter, dose, composition, feature, condition, or process contrast",
                "decision-relevant measurable readout baseline",
            ],
            "adversarial_requirements": [
                "null or non-directional effects",
                "alternative mechanism explanations",
                "measurement artifacts or model misspecification",
                "failure modes and reversal effects",
                "heterogeneous effects across boundary conditions",
            ],
            "rewrite_reason": (
                "The original objective is academic but framed like a review introduction; the rewrite "
                "keeps the domain and named objects while requiring parameterized variables, concrete "
                "readouts, explicit comparisons, boundary conditions, and falsification pressure."
            ),
            "scope_preservation": (
                "Preserves the user's original field, named objects, methods, and mechanisms; only adds "
                "variable resolution, measurable endpoints, comparison, boundary, adverse/null paths, "
                "and falsification pressure."
            ),
            "original_objective_preserved": original_objective,
        }
    subject_scope = (
        "candidate strategies, interventions, models, materials, policies, or workflows"
        if subject == "candidate"
        else f"{subject} strategies, interventions, models, materials, policies, or workflows"
    )
    return {
        "academic_objective": (
            "Under data or measurement uncertainty, system/material/population heterogeneity, "
            "substitution or rebound burden, resource competition, and implementation constraints, "
            f"which {subject_scope} produce net improvements in measurable outcomes compared with "
            "explicit baselines, and under what boundary conditions do adverse or reversal "
            "mechanisms offset the expected effect?"
        ),
        "reframing_type": "academic_reframing_required",
        "reframing_axes": [
            "data or measurement uncertainty",
            "system, material, population, or process heterogeneity",
            "substitution or rebound burden",
            "resource competition",
            "implementation and scale-up constraints",
            "measurable endpoint definition",
        ],
        "baseline_requirements": [
            "single-strategy or single-component baseline",
            "current-standard or usual-practice baseline",
            "no-intervention, static-model, or status-quo baseline when appropriate",
            "decision-relevant measurable outcome baseline",
        ],
        "adversarial_requirements": [
            "negative evidence",
            "null or reversal effects",
            "substitution and rebound effects",
            "burden shifting",
            "resource competition",
            "implementation failure modes",
            "heterogeneous effects across boundary conditions",
        ],
        "rewrite_reason": (
            "The original objective is public-facing or solution-list-like; the rewrite turns it "
            "into a constrained, comparative, falsifiable scientific parent question without "
            "changing the declared domain."
        ),
        "scope_preservation": (
            "Preserves the user's original domain, named objects, candidate strategies, and explicit "
            "constraints while requiring baselines, adverse paths, boundary conditions, measurable "
            "endpoints, and falsification pressure."
        ),
        "original_objective_preserved": original_objective,
    }


def _normalize_academic_reframing_payload(
    payload: dict[str, Any],
    *,
    original_objective: str,
    audit: dict[str, Any],
    extractor: str,
) -> dict[str, Any]:
    academic_objective = re.sub(r"\s+", " ", str(payload.get("academic_objective") or "").strip())
    if not academic_objective:
        academic_objective = (
            "Under explicit uncertainty, boundary conditions, adverse trade-offs, and baseline "
            "comparisons, which intervention or strategy produces a net improvement in measurable "
            "decision-relevant outcomes?"
        )
    axes = payload.get("reframing_axes")
    baselines = payload.get("baseline_requirements")
    adversarial = payload.get("adversarial_requirements")
    reframing_type = str(
        payload.get("reframing_type")
        or audit.get("recommended_action")
        or "academic_reframing_required"
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if reframing_type in {"academic_operationalisation", "operationalization_required"}:
        reframing_type = "academic_operationalization"
    if reframing_type not in {"academic_reframing_required", "academic_operationalization"}:
        reframing_type = "academic_reframing_required"
    return {
        "schema_version": "academic_reframing_v1",
        "applied": True,
        "reframing_type": reframing_type,
        "original_objective": str(original_objective or ""),
        "academic_objective": academic_objective,
        "academic_rewrite": academic_objective,
        "rewrite_reason": str(payload.get("rewrite_reason") or payload.get("reason") or "")[:1000],
        "scope_preservation": str(payload.get("scope_preservation") or "")[:1000],
        "reframing_axes": [str(item)[:160] for item in (axes if isinstance(axes, list) else []) if str(item).strip()][:8],
        "baseline_requirements": [str(item)[:180] for item in (baselines if isinstance(baselines, list) else []) if str(item).strip()][:8],
        "adversarial_requirements": [str(item)[:180] for item in (adversarial if isinstance(adversarial, list) else []) if str(item).strip()][:8],
        "original_objective_preserved": str(payload.get("original_objective_preserved") or original_objective or ""),
        "framing_audit": audit,
        "extractor": extractor,
    }


def academic_reframe_project_objective(
    *,
    original_objective: str,
    domain: str = "",
    detected_weaknesses: list[str] | None = None,
    framing_audit: dict[str, Any] | None = None,
    research_brief: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Rewrite a public/problem-list objective into a scoped academic question."""

    objective = str(original_objective or "").strip()
    domain_text = str(domain or "").strip()
    audit = framing_audit if isinstance(framing_audit, dict) else {}
    weaknesses = list(detected_weaknesses or audit.get("detected_weaknesses") or [])
    reframing_type = str(audit.get("recommended_action") or "academic_reframing_required").strip().lower()
    reframing_type = reframing_type.replace("-", "_").replace(" ", "_")
    if reframing_type in {"academic_operationalisation", "operationalization_required"}:
        reframing_type = "academic_operationalization"
    if reframing_type not in {"academic_reframing_required", "academic_operationalization"}:
        reframing_type = "academic_reframing_required"
    if use_llm:
        payload = {
            "original_objective": objective,
            "domain": domain_text,
            "reframing_type": reframing_type,
            "detected_weaknesses": weaknesses,
            "research_brief": str(research_brief or "")[:6000],
        }
        try:
            raw = call_llm_json(
                system=(
                    "You rewrite broad public-facing or under-operationalized academic research objectives into academically rigorous "
                    "parent questions. Preserve the user's research domain and original scope; do not "
                    "invent a different topic. Add comparative baselines, adverse/reversal paths, boundary "
                    "conditions, measurable endpoints, parameter-level variables, and falsification pressure. "
                    "For academic review-introduction inputs, do not call them non-academic; operationalize "
                    "them into testable variables and readouts. Return JSON only."
                ),
                prompt=(
                    "Rewrite the objective only if needed for rigorous SH decomposition. The rewrite must "
                    "turn either (a) a slogan or solution list into a constrained, comparative, falsifiable "
                    "scientific question, or (b) an academic review-introduction into an operationalized "
                    "parent question with parameterized variables, concrete measurable endpoints, baselines, "
                    "boundary conditions, alternative/null/adverse mechanisms, and falsification. Preserve "
                    "original_objective verbatim in original_objective_preserved and state scope_preservation "
                    "so a user can roll back if they disagree. Scope should cover natural sciences, engineering, "
                    "health, environmental, materials, mathematical, agricultural, and computational fields; "
                    "ignore humanities/social-science-only framing unless the user's domain explicitly requires it.\n\n"
                    f"INPUT_JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                    "Return exactly one JSON object with keys: academic_objective, reframing_axes, "
                    "baseline_requirements, adversarial_requirements, original_objective_preserved, "
                    "rewrite_reason, scope_preservation, reframing_type."
                ),
                max_tokens=8000,
            )
            return _normalize_academic_reframing_payload(
                raw,
                original_objective=objective,
                audit=audit,
                extractor="llm",
            )
        except Exception as exc:
            raw = _domain_general_academic_reframing(
                objective,
                domain=domain_text,
                research_brief=research_brief,
                reframing_type=reframing_type,
            )
            raw["rewrite_reason"] = (
                f"{raw.get('rewrite_reason') or ''} Heuristic fallback after LLM failure."
            ).strip()
            normalized = _normalize_academic_reframing_payload(
                raw,
                original_objective=objective,
                audit=audit,
                extractor="heuristic_after_llm_failure",
            )
            normalized["llm_error"] = str(exc)[:300]
            return normalized
    raw = _domain_general_academic_reframing(
        objective,
        domain=domain_text,
        research_brief=research_brief,
        reframing_type=reframing_type,
    )
    raw["rewrite_reason"] = (
        f"{raw.get('rewrite_reason') or ''} Deterministic academic reframing fallback."
    ).strip()
    return _normalize_academic_reframing_payload(
        raw,
        original_objective=objective,
        audit=audit,
        extractor="heuristic",
    )


def optimize_scientific_retrieval_queries(
    *,
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
    original_query: str,
    attempted_queries: list[str] | None = None,
    round_index: int = 1,
    max_queries: int = 5,
) -> dict[str, Any]:
    """Use the external science LLM only as a constrained query optimizer.

    The returned synonyms and queries are retrieval hypotheses.  They have no
    authority to mutate the sub-hypothesis, PaperGraph, or scientific facts;
    a deterministic validator must still admit every query before execution.
    """

    max_items = max(1, min(5, int(max_queries or 5)))
    immutable_contract = {
        key: alignment_contract.get(key)
        for key in (
            "project_id",
            "sub_hypothesis_id",
            "focus",
            "scientific_object",
            "primary_field",
            "evidence_mode",
            "declared_research_mode",
            "scientific_object_phrases",
            "scientific_object_terms",
            "project_context_phrases",
            "project_context_anchor_terms",
            "independent_variable",
            "dependent_variables",
            "comparison",
            "falsification_condition",
            "input_phrases",
            "input_terms",
            "mechanism_phrases",
            "mechanism_terms",
            "outcome_phrases",
            "outcome_terms",
            "evidence_paths",
            "object_maturity_status",
            "object_maturity_retrieval_mode",
            "direct_core_evidence_allowed",
            "object_maturity_audit",
            "excluded_nearby_objects",
            "explicit_exclusion_terms",
            "required_evidence_roles",
        )
    }
    evidence_standard = alignment_contract.get("evidence_standard")
    if isinstance(evidence_standard, dict):
        immutable_contract["evidence_standard"] = {
            key: evidence_standard.get(key)
            for key in (
                "id",
                "accepted_core_designs",
                "support_designs",
                "excluded_as_core",
                "claim_strength_cap",
            )
        }
    causal_contract = alignment_contract.get("causal_contract")
    if isinstance(causal_contract, dict):
        immutable_contract["causal_contract"] = {
            key: causal_contract.get(key)
            for key in (
                "constraint_type",
                "pivotal_mechanism",
                "supporting_mediators",
                "outcome",
                "boundary_conditions",
            )
        }
    optimizer_input = {
        "round": int(round_index),
        "original_query": str(original_query or "")[:1200],
        "attempted_queries": [str(item)[:1200] for item in (attempted_queries or [])[-12:]],
        "immutable_alignment_contract": immutable_contract,
        "failure_diagnostics": failure_diagnostics,
        "maximum_queries": max_items,
    }
    return call_llm_json(
        system=(
            "You optimize academic literature retrieval after a failed search/import round. "
            "Return JSON only. The alignment contract is immutable: never change the scientific object, "
            "sub-hypothesis, input, mechanism, outcome, context, or exclusions. You may expand synonyms, "
            "use database terminology, change Boolean structure, operationalize an existing abstract term, "
            "and target a missing evidence layer/lane as metadata. Evidence roles and layers are routing "
            "metadata, not mandatory words in a provider query: never inject labels such as 'causal validation', "
            "'mechanism discovery', or 'target layer' unless they are explicit scientific concepts in the immutable "
            "contract. Do not turn treatment efficacy into evidence for a "
            "scientific structure unless that endpoint is in the contract. Any proposed synonym is only a "
            "search expansion hypothesis, never a scientific fact. Do not invent papers or evidence. "
            "If failure_diagnostics.provider_execution_replan is present, it is a provider-and-branch "
            "execution diagnosis, not a scientific failure. Replan only the listed branch_replan_requests: "
            "each replacement must cite its replan_of_branch exactly, must be a fresh query rather than a retry, "
            "must preserve the immutable object and required scientific axes, and must not resubmit a branch that "
            "already has a semantically conformant provider receipt. Treat failed providers as quarantined for that "
            "branch; do not repair the scientific contract or invent a provider-specific topical term. "
            "If direct_core_evidence_allowed=false or object_maturity_retrieval_mode=component_bridge_boundary, "
            "the declared final scientific_object is not a mature direct literature identity. In that case never "
            "generate direct-core validation queries for the final object and never treat components, platforms, "
            "model systems, mediators, assays, or readouts as aliases of that final object. Route retrieval through "
            "component_evidence, translational_bridge, boundary_or_safety_evidence, or context_review only. "
            "Use role-shaped retrieval: L0_review/context queries may use review, survey, progress, perspective, "
            "overview, framework, or formal-model language; L2_top_latest and L4_regular queries must not use those "
            "context-only markers unless they are literal scientific objects in the immutable contract."
        ),
        prompt=(
            "Diagnose the supplied retrieval failure and produce at most "
            f"{max_items} English, bounded, non-preprint academic queries. Every query must retain at least "
            "one exact scientific-object anchor or declared semantic-equivalent object anchor from the immutable "
            "contract and at least one scientific-axis "
            "anchor from the declared input, pivotal mechanism, outcome, boundary, or moderator. Target only "
            "L0_review, L1_milestone, L2_top_latest, or L4_regular. The target layer and lane are output metadata; "
            "do not use their internal labels as required literal phrases. "
            "For target_layer=L0_review, context words such as review/survey/overview/progress/perspective/framework "
            "are allowed. For target_layer=L2_top_latest or L4_regular, do not use review, survey, progress, "
            "perspective, advances, current trends, overview, theoretical framework, formal model, tutorial, or "
            "framework as positive retrieval terms. "
            "For core_validation / CAUSAL_VALIDATION queries, bind the object to a study/design anchor plus a "
            "measurable endpoint or comparison, e.g. controlled study, randomized trial, cohort, assay, in vivo, "
            "in vitro, perturbation, dose response, treatment, control group, compared with, measurable endpoint. "
            "Do not use placeholder endpoints such as visualization, understanding, function, performance, "
            "quality, effectiveness, reliable results, reproducible results, or reliable and reproducible results "
            "as the only endpoint. If the current contract contains such broad wording, operationalize the query "
            "with concrete metrics such as resolution, precision, error rate, sensitivity, specificity, AUC, RMSE, "
            "signal-to-noise, artifact rate, yield, potency, toxicity, leakage mass, or carbon footprint, while "
            "preserving the immutable scientific scope. "
            "If object_maturity_retrieval_mode=component_bridge_boundary, use only typed component-bridge anchors "
            "from scientific_object_anchor_policy/object_maturity_audit: object_anchors, method_or_platform_anchors, "
            "readout_anchors, and model_system_anchors. Do not recover anchors from legacy flat fields such as "
            "component_evidence_anchors, translational_bridge_anchors, boundary_or_safety_anchors, or component_anchor_group. "
            "Return component_evidence, translational_bridge, "
            "boundary_or_safety_evidence, or context_review roles; do not return core_validation as a direct claim "
            "against the immature final object. "
            "For supporting_mechanism / MECHANISM_DISCOVERY queries, use assay, perturbation, knockout/knockdown, "
            "inhibition, ablation, in vivo/in vitro, functional readout, or quantitative measurement terms. "
            "For predictive_generalization / PREDICTIVE_VALIDATION queries, use external validation, validation "
            "cohort, calibration, discrimination, baseline comparison, benchmark, out-of-sample, or decision-utility "
            "terms. "
            "For adverse_or_reversal / ADVERSE_OR_REVERSAL_EVIDENCE queries, treat opposing evidence as in-scope: "
            "bind the same scientific object to a measurable endpoint plus adverse, reversal, null, rebound, "
            "substitution, burden-shifting, resource-competition, robustness-failure, toxicity, or implementation-failure "
            "mechanisms. Do not make adverse queries topic-only; they still require object, endpoint, and comparison, "
            "boundary, or negative-mechanism anchors. For every intervention, strategy, material, platform, model, "
            "or policy-like SH, include at least one adverse/reversal branch unless the SH is purely descriptive; "
            "never return only supportive branches when the contract contains an evidence_path for adverse_or_reversal. "
            "The adverse path is not off-topic: output evidence_path_role='adverse_or_reversal' and target_lane="
            "'ADVERSE_OR_REVERSAL_EVIDENCE' when the query asks whether the same object weakens, reverses, fails, "
            "or shifts burdens under a measurable comparison or boundary condition. Example shape only (do not copy "
            "the domain unless the contract is about that domain): "
            '{"target_layer":"L4_regular","target_lane":"ADVERSE_OR_REVERSAL_EVIDENCE",'
            '"evidence_path_role":"adverse_or_reversal",'
            '"query":"plastic ban substitution effect lifecycle burden carbon footprint reuse threshold",'
            '"rationale":"Searches for evidence that the policy may worsen net lifecycle impact through substitute products."} '
            "Use explicit NOT clauses only for declared nearby-object exclusions; do not broaden by deleting "
            "the object anchor. Prefer separate context, mechanism-support, core-validation, predictive-validation, "
            "adverse/reversal, and boundary queries instead of one oversized query. RELATED_FULLTEXT_COUNT_SHORTFALL "
            "is the workflow-blocking corpus failure: it means the SH has fewer than 10 unique, related, usable "
            "full texts, so generate broad corpus/diversity branches bound to the object plus one relevant axis. "
            "COMPATIBLE_DIRECT_CORE_SHORTFALL or CAUSAL_CHAIN_CORE_SHORTFALL are claim-limiting diagnostics, not "
            "workflow blockers: generate a narrow core branch using primary designs such as controlled comparison, "
            "causal identification, dose-response, intervention, or direct negative/falsification tests, but do not "
            "prevent auxiliary/context evidence from entering gap synthesis. Layer mix, alignment conversion, "
            "standard-core design counts, evidence lanes, and evidence-role diversity are diagnostics only and must "
            "not be returned as blocking failure classes. If the diagnostic funnel shows high duplicate pressure, do not produce synonym-only variants "
            "(for example immune response -> immunological response). Change at least one evidence_path, endpoint, "
            "experimental system, comparison, population/material/platform, provider/layer target, or strong object "
            "anchor while preserving the immutable object scope. "
            "If the diagnostics show COARSE_PREFILTER_OBJECT_MISMATCH caused by a narrow method or measurement "
            "object, use only semantic equivalents already supported by the contract or user brief, such as acronyms, "
            "orthographic variants, complementary measurement-system names, or method-platform aliases. Do not treat "
            "related context words alone as core object proof; route related-context experimental papers to auxiliary "
            "or pending-fulltext evidence roles. "
            "If declared_research_mode is LABORATORY_CONSTRAINT and the failed SH/query uses generic terms such "
            "as stability, storage, temperature, pressure, humidity, shelf life, operating condition, or regime, "
            "operationalize them into the relevant laboratory constraint evidence: controlled condition perturbation, "
            "assay/characterization readout, degradation or failure-mode measurement, accelerated stability or stress "
            "test, potency/activity/retention/efficiency/yield readout, and boundary-condition validation. For such "
            "failures, avoid review-only wording like requirements, overview, challenge, or guideline unless targeting "
            "L0_review explicitly. "
            "When INPUT_JSON.failure_diagnostics.provider_execution_replan.branch_replan_requests is nonempty, "
            "produce replacements only for those branch IDs. Set replan_of_branch to the exact requested branch "
            "ID. The failed receipts identify provider syntax/anchor-loss constraints; use them to avoid repeating "
            "the failed wording, while retaining at least one contract object anchor and one declared scientific axis. "
            "Do not output a query for a branch that has a conformant provider receipt.\n\n"
            f"INPUT_JSON:\n{json.dumps(optimizer_input, ensure_ascii=False, indent=2, default=str)[:18000]}\n\n"
            "Return exactly one object with this schema:\n"
            "{\n"
            '  "failure_class":"RELATED_FULLTEXT_COUNT_SHORTFALL|COMPATIBLE_DIRECT_CORE_SHORTFALL|CAUSAL_CHAIN_CORE_SHORTFALL",\n'
            '  "preserved_anchors":["..."],\n'
            '  "proposed_synonyms":[{"source":"...","candidate":"...","status":"hypothesis_search_term_not_scientific_fact"}],\n'
            '  "queries":[{"replan_of_branch":"required only for provider_execution_replan; exact requested branch ID","target_layer":"L0_review|L1_milestone|L2_top_latest|L4_regular","target_lane":"THEORETICAL_FRAMEWORK|MECHANISM_DISCOVERY|CAUSAL_VALIDATION|PREDICTIVE_VALIDATION|ADVERSE_OR_REVERSAL_EVIDENCE|BOUNDARY_OR_NEGATIVE_EVIDENCE","evidence_path_role":"context_review|supporting_mechanism|core_validation|predictive_generalization|adverse_or_reversal|boundary_or_generalization|component_evidence|translational_bridge|boundary_or_safety_evidence","query":"...","rationale":"..."}],\n'
            '  "negative_terms":["..."],\n'
            '  "expected_improvement":"..."\n'
            "}"
        ),
        max_tokens=1800,
        fallback_list_key="queries",
    )


def refine_contract_calibration_queries_from_metadata_batch(
    *,
    alignment_contract: dict[str, Any],
    original_plan: list[dict[str, Any]],
    metadata_batch: dict[str, Any],
    round_index: int,
) -> dict[str, Any]:
    """Refine a failed lexical-calibration plan from a bounded paper batch.

    This is intentionally narrower than the ordinary query optimizer. The LLM
    may only select optional terms already supplied by the deterministic
    metadata batch; it may not add role labels, study-template words, or a
    guessed field vocabulary. The caller still validates every output query.
    """

    immutable_contract = {
        key: alignment_contract.get(key)
        for key in (
            "project_id",
            "sub_hypothesis_id",
            "focus",
            "scientific_object",
            "scientific_object_phrases",
            "scientific_object_terms",
            "independent_variable",
            "input_phrases",
            "input_terms",
            "mechanism_phrases",
            "mechanism_terms",
            "outcome_phrases",
            "outcome_terms",
            "comparison",
            "falsification_condition",
            "excluded_nearby_objects",
            "query_forbidden_terms",
        )
    }
    batch = metadata_batch if isinstance(metadata_batch, dict) else {}
    request = {
        "round": int(round_index),
        "immutable_alignment_contract": immutable_contract,
        "original_calibration_plan": [
            {
                "branch": str(item.get("branch") or ""),
                "query": str(item.get("query") or ""),
                "target_layer": str(item.get("target_layer") or ""),
                "target_lane": str(item.get("target_lane") or ""),
            }
            for item in (original_plan or [])
            if isinstance(item, dict)
        ][:3],
        "metadata_batch": {
            "status": str(batch.get("status") or ""),
            "papers": [
                dict(item)
                for item in (batch.get("papers") or [])
                if isinstance(item, dict)
            ][:8],
            "contract_terms": [str(item) for item in (batch.get("contract_terms") or [])][:96],
            "permitted_refinement_terms": [
                str(item) for item in (batch.get("permitted_refinement_terms") or [])
            ][:96],
            "term_source_ids": dict(batch.get("term_source_ids") or {}),
            "policy": str(batch.get("policy") or ""),
        },
    }
    return call_llm_json(
        system=(
            "You refine a failed academic lexical-calibration query after an auditable plan/execution mismatch. "
            "Return JSON only. The alignment contract is immutable. Do not introduce generic retrieval words, "
            "experimental templates, evidence-role labels, or a guessed disciplinary vocabulary. A new query term "
            "is allowed only when it appears verbatim in permitted_refinement_terms, which was extracted from a "
            "small paper batch that already matched the declared scientific object and input. Do not use any other "
            "term from paper titles or abstracts. If the batch exposes no usable non-generic term, return an empty "
            "queries list and status CONTRACT_REBUILD_REQUIRED. Preserve an exact declared object phrase and an "
            "exact declared input phrase in every query. This task changes retrieval phrasing only; it never changes "
            "the scientific contract or claims that a source supports a result."
        ),
        prompt=(
            "The original calibration plan was not executed as planned. Using only the supplied immutable contract "
            "and permitted_refinement_terms, return zero to three precise replacement queries. Each query must retain "
            "the declared object and input phrases, and may append at most two permitted non-generic terms. Do not "
            "append words such as experiment, study, review, theoretical, formal, validation, model, framework, "
            "analysis, or mechanism unless they are literal contract terms (they still will be rejected if generic). "
            "Do not use terms absent from the allowlist. Cite the source_candidate_ids responsible for every added "
            "term in rationale metadata.\n\n"
            f"INPUT_JSON:\n{json.dumps(request, ensure_ascii=False, indent=2, default=str)[:18000]}\n\n"
            "Return exactly one object with this schema:\n"
            "{\n"
            '  "failure_class":"RELATED_FULLTEXT_COUNT_SHORTFALL|COMPATIBLE_DIRECT_CORE_SHORTFALL",\n'
            '  "repair_status":"REFINED_QUERIES_READY|CONTRACT_REBUILD_REQUIRED",\n'
            '  "queries":[{"target_layer":"L2_top_latest|L4_regular","target_lane":"THEORETICAL_OR_FORMAL_EVIDENCE|COMPUTATIONAL_MODEL_DISCRIMINATION|MECHANISM_DISCOVERY|CAUSAL_VALIDATION|PREDICTIVE_VALIDATION","evidence_path_role":"contract_lexical_calibration","query":"...","rationale":"...","source_candidate_ids":["..."]}],\n'
            '  "expected_improvement":"..."\n'
            "}"
        ),
        max_tokens=1200,
        fallback_list_key="queries",
    )


def reassess_subhypothesis_for_low_admission(
    *,
    sub_hypothesis: dict[str, Any],
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
    original_query: str,
    attempted_queries: list[str] | None = None,
    round_index: int = 1,
) -> dict[str, Any]:
    """Diagnose low yield and propose a retrieval plan or shadow-only patch."""

    immutable_scope = {
        "project_id": alignment_contract.get("project_id"),
        "sub_hypothesis_id": alignment_contract.get("sub_hypothesis_id"),
        "focus": str(sub_hypothesis.get("focus") or ""),
        "scientific_object": alignment_contract.get("scientific_object"),
        "excluded_nearby_objects": list(
            alignment_contract.get("excluded_nearby_objects") or []
        ),
        "required_evidence_roles": list(
            alignment_contract.get("required_evidence_roles") or []
        ),
        "evidence_mode": alignment_contract.get("evidence_mode"),
    }
    active_contract = {
        "independent_variable": sub_hypothesis.get("independent_variable"),
        "dependent_variables": list(sub_hypothesis.get("dependent_variables") or []),
        "causal_chain": list(sub_hypothesis.get("causal_chain") or []),
        "evidence_paths": list(sub_hypothesis.get("evidence_paths") or []),
        "causal_contract": dict(sub_hypothesis.get("causal_contract") or {}),
        "retrieval_query": str(original_query or ""),
    }
    reviewer_input = {
        "round": int(round_index),
        "immutable_scope": immutable_scope,
        "active_scientific_contract": active_contract,
        "failure_diagnostics": failure_diagnostics,
        "attempted_queries": [
            str(item)[:1200] for item in (attempted_queries or [])[-12:]
        ],
    }
    return call_llm_json(
        system=(
            "You diagnose a low-yield literature retrieval round for a persisted scientific "
            "sub-hypothesis. Return JSON only. Preserve immutable scope exactly: never change "
            "focus, scientific object, project direction, excluded objects, evidence mode, or "
            "evidence-role policy. Default to change_level=retrieval_only: produce bounded, "
            "scientifically anchored query branches without rewriting variables or the causal "
            "chain. An evidence_path change may only clarify queries for existing roles. Use "
            "change_level=scientific_contract only when the diagnostics show high retrieval "
            "coverage but persistent semantic misalignment; it is a candidate for shadow "
            "validation, never an applied fact. Do not use a full-text, provider, or temporary "
            "access failure as evidence that the scientific model is wrong. Do not broaden by "
            "deleting scope anchors, add a neighboring research object, invent facts, or claim "
            "that a proposed term is established evidence."
        ),
        prompt=(
            "First classify the failure: resolver/provider, duplicate-query space, insufficient "
            "scientific vocabulary, or high-recall semantic mismatch. For retrieval_only, return "
            "one to three English query branches that retain the exact object anchor plus one "
            "scientific axis already declared by the active contract, or a semantic-equivalent object "
            "anchor already present in the contract/user brief. Tighten an over-broad query "
            "with field terminology or a documented synonym; do not lengthen it by requiring every "
            "mediator in the causal chain. target_layer and target_lane are metadata. Do not add "
            "system labels such as causal validation or mechanism discovery as literal requirements. "
            "When a strategy/intervention/model/material/policy-like contract was previously searched only "
            "supportively, add an adverse_or_reversal branch unless the SH is purely descriptive; adverse "
            "branches must preserve the same scientific object and include measurable endpoint plus comparison, "
            "boundary, null, reversal, trade-off, rebound, burden-shifting, or implementation-failure language. "
            "Do not preserve generic endpoints such as visualization, understanding, function, performance, "
            "quality, effectiveness, reliable results, reproducible results, or reliable and reproducible results "
            "as the only query endpoint; use concrete measurement metrics already implied by the contract or "
            "discipline instead. "
            "If object-mismatch diagnostics come from a narrow measurement method, related-context experimental "
            "papers may be routed as auxiliary/pending-fulltext candidates, but a related context object alone must "
            "not be described as core evidence for the declared causal chain. "
            "For scientific_contract, leave active fields untouched and supply only a compact patch "
            "plus all four invariants; the controller will save it as shadow_required.\n\n"
            f"INPUT_JSON:\n{json.dumps(reviewer_input, ensure_ascii=False, indent=2, default=str)[:18000]}\n\n"
            "Return exactly one object with this schema:\n"
            "{\n"
            '  "preserved_scope":{"focus":"exact input focus","scientific_object":"exact input scientific object","excluded_nearby_objects":["..."]},\n'
            '  "change_level":"retrieval_only|evidence_path|scientific_contract",\n'
            '  "retrieval_strategy":{"queries":[{"target_layer":"L0_review|L1_milestone|L2_top_latest|L4_regular","target_lane":"THEORETICAL_FRAMEWORK|MECHANISM_DISCOVERY|CAUSAL_VALIDATION|ADVERSE_OR_REVERSAL_EVIDENCE|BOUNDARY_OR_NEGATIVE_EVIDENCE|PREDICTIVE_VALIDATION","evidence_path_role":"context_review|supporting_mechanism|core_validation|predictive_generalization|adverse_or_reversal|boundary_or_generalization","query":"specific English scientific query","rationale":"retrieval diagnosis"}]},\n'
            '  "scientific_contract_patch":{"parent_decision_link":"...","constraint_type":"...","pivotal_mechanism":"...","supporting_mediators":["..."],"outcome":"...","boundary_conditions":["..."],"confounders_or_alternatives":["..."],"rationale":"..."},\n'
            '  "invariants":{"parent_decision_link_preserved":true,"exclusive_objects_preserved":true,"outcome_preserved_or_explicitly_revised":true,"no_cross_sh_object_leakage":true},\n'
            '  "removed_generic_terms":["..."],\n'
            '  "added_specific_terms":["..."],\n'
            '  "rationale":"brief retrieval diagnosis"\n'
            "}"
        ),
        max_tokens=1800,
    )

def get_science_llm_client() -> Any:
    extractor = SCIENCE_LLM_EXTRACTOR.strip().lower()
    if extractor in {"qwen", "dashscope"}:
        if not QWEN_API_KEY:
            raise RuntimeError("Science LLM extractor is qwen, but QWEN_API_KEY/DASHSCOPE_API_KEY is not set.")
        try:
            from .qwen_adapter import QwenClient
        except ImportError:
            from qwen_adapter import QwenClient
        return QwenClient(api_key=QWEN_API_KEY, model=QWEN_MODEL_ID, api_base=QWEN_API_BASE or "")
    if extractor in {"off", "none", "disabled"}:
        raise RuntimeError("Science LLM extractor is disabled.")
    try:
        from .llm import get_client
    except ImportError:
        from llm import get_client
    return get_client()

def render_llm_response_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or ""))
            else:
                chunks.append(str(item))
        return "\n".join(chunk for chunk in chunks if chunk)
    return str(content)

def parse_json_object_from_text_with_diagnostics(
    text: str,
    fallback_list_key: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
    root_object_unbalanced = bool(
        stripped.startswith("{") and not first_balanced_object(stripped)
    )
    candidates: list[tuple[str, str]] = [("full_response", stripped)]
    candidates.extend(
        ("fenced_json", candidate)
        for candidate in fenced_json_blocks(stripped)
    )
    candidates.append(("balanced_object", first_balanced_object(stripped)))
    if fallback_list_key:
        candidates.append((
            "keyed_partial_array",
            extract_keyed_partial_array_object(stripped, fallback_list_key),
        ))
    if stripped.startswith("["):
        candidates.append(("top_level_array", first_balanced_array(stripped)))
    candidates.extend(
        (f"{mode}_json_repair", json_repair_candidates(candidate))
        for mode, candidate in list(candidates)
        if candidate
    )
    for mode, candidate in candidates:
        if not candidate:
            continue
        parsed = parse_json_candidate(candidate)
        if parsed is None:
            continue
        if isinstance(parsed, dict):
            return parsed, {
                "recovery_mode": mode,
                "root_object_unbalanced": root_object_unbalanced,
                "wrapped_top_level_list": False,
            }
        if (
            fallback_list_key
            and isinstance(parsed, list)
            and (
                mode.startswith("top_level_array")
                or mode.startswith("fenced_json")
                or (mode.startswith("full_response") and stripped.startswith("["))
            )
        ):
            return {fallback_list_key: parsed}, {
                "recovery_mode": mode,
                "root_object_unbalanced": root_object_unbalanced,
                "wrapped_top_level_list": True,
            }
    return {}, {
        "recovery_mode": "failed",
        "root_object_unbalanced": root_object_unbalanced,
        "wrapped_top_level_list": False,
    }


def parse_json_object_from_text(text: str, fallback_list_key: str = "") -> dict[str, Any]:
    parsed, _ = parse_json_object_from_text_with_diagnostics(
        text,
        fallback_list_key=fallback_list_key,
    )
    return parsed


def parse_json_candidate(candidate: str) -> Any | None:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                return None

def fenced_json_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", str(text or ""), flags=re.IGNORECASE | re.DOTALL):
        block = match.group(1).strip()
        if block:
            blocks.append(block)
    return blocks

def json_repair_candidates(text: str) -> str:
    candidate = str(text or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    return candidate

def extract_keyed_partial_array_object(text: str, key: str) -> str:
    array_text = extract_keyed_partial_array(text, key)
    if not array_text:
        return ""
    return f'{{"{key}": {array_text}}}'

def extract_keyed_partial_array(text: str, key: str) -> str:
    source = str(text or "")
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', source)
    if not match:
        return ""
    start = source.find("[", match.start())
    if start < 0:
        return ""
    complete_items = extract_complete_json_objects_from_array(source[start + 1 :])
    if not complete_items:
        return ""
    return "[" + ",".join(complete_items) + "]"

def extract_complete_json_objects_from_array(text: str) -> list[str]:
    items: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(str(text or "")):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : index + 1]
                parsed = parse_json_candidate(json_repair_candidates(candidate))
                if parsed is None:
                    start = -1
                    continue
                if isinstance(parsed, dict):
                    items.append(json.dumps(parsed, ensure_ascii=False))
                start = -1
            continue
        if char == "]" and depth == 0:
            break
    return items

def first_balanced_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""

def first_balanced_array(text: str) -> str:
    start = text.find("[")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""

def normalize_llm_paper_structure(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import normalize_gap_signals
        from ._literature_import import normalize_doi
        from ._utils import scalar, string_list
    except ImportError:
        from _gap_detection import normalize_gap_signals
        from _literature_import import normalize_doi
        from _utils import scalar, string_list
    return {
        "title": scalar(payload.get("title")),
        "citation": scalar(payload.get("citation")),
        "authors": string_list(payload.get("authors")),
        "year": scalar(payload.get("year")),
        "venue": scalar(payload.get("venue")),
        "doi": normalize_doi(scalar(payload.get("doi"))),
        "arxiv_id": scalar(payload.get("arxiv_id") or payload.get("arxiv")),
        "abstract": scalar(payload.get("abstract")),
        "conclusion": scalar(payload.get("conclusion")),
        "strengths": string_list(payload.get("strengths")),
        "improvements": string_list(payload.get("improvements") or payload.get("limitations")),
        "method": scalar(payload.get("method")),
        "scenario": scalar(payload.get("scenario")),
        "benchmark": scalar(payload.get("benchmark")),
        "contribution": scalar(payload.get("contribution")),
        "limitation": scalar(payload.get("limitation")),
        "causal_chains": normalize_causal_chains(payload.get("causal_chains")),
        "gap_signals": normalize_gap_signals(
            [
                item if isinstance(item, dict) else {"signal_type": "gap_signal", "text": scalar(item)}
                for item in (payload.get("gap_signals") if isinstance(payload.get("gap_signals"), list) else [])
            ]
            + [
                {"signal_type": "limitation", "text": item, "evidence_type": "author_opinion"}
                for item in string_list(payload.get("limitations"))
            ]
        ),
    }


def normalize_causal_chains(value: Any) -> list[dict[str, Any]]:
    try:
        from ._utils import scalar, string_list
    except ImportError:
        from _utils import scalar, string_list
    if not isinstance(value, list):
        return []
    chains: list[dict[str, Any]] = []
    for raw_chain in value:
        if not isinstance(raw_chain, dict):
            continue
        trigger = scalar(raw_chain.get("trigger") or raw_chain.get("condition") or raw_chain.get("input"))
        outcome = scalar(raw_chain.get("outcome") or raw_chain.get("result") or raw_chain.get("effect"))
        raw_steps = raw_chain.get("steps") or raw_chain.get("intermediate_steps") or []
        if isinstance(raw_steps, (str, int, float)):
            raw_steps = [raw_steps]
        steps: list[dict[str, Any]] = []
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                if isinstance(raw_step, dict):
                    claim = scalar(raw_step.get("claim") or raw_step.get("step") or raw_step.get("text"))
                    evidence = scalar(raw_step.get("evidence") or raw_step.get("evidence_excerpt"))
                    evidence_type = scalar(raw_step.get("evidence_type")) or "reported_unclassified"
                else:
                    claim = scalar(raw_step)
                    evidence = ""
                    evidence_type = "reported_unclassified"
                if claim:
                    step = {"claim": claim, "evidence": evidence, "evidence_type": evidence_type}
                    for key in ("relation", "polarity", "modality", "source_location"):
                        value = raw_step.get(key) if isinstance(raw_step, dict) else None
                        if isinstance(value, dict):
                            step[key] = dict(value)
                        elif scalar(value):
                            step[key] = scalar(value)
                    steps.append(step)
        observables = string_list(raw_chain.get("observables") or raw_chain.get("observable_signals"))
        interventions = string_list(raw_chain.get("interventions") or raw_chain.get("manipulations"))
        if not trigger and not steps and not outcome:
            continue
        chain = {
            "chain_id": scalar(raw_chain.get("chain_id")) or f"chain_{len(chains) + 1}",
            "trigger": trigger,
            "trigger_evidence": scalar(raw_chain.get("trigger_evidence")),
            "steps": steps,
            "outcome": outcome,
            "outcome_evidence": scalar(raw_chain.get("outcome_evidence")),
            "observables": observables,
            "interventions": interventions,
            "confidence": raw_chain.get("confidence") if isinstance(raw_chain.get("confidence"), (int, float)) else None,
        }
        raw_context = raw_chain.get("context") or raw_chain.get("study_context")
        if isinstance(raw_context, dict):
            context = {
                key: scalar(raw_context.get(key))
                for key in ("research_object", "species_or_system", "model_or_sample", "stage_or_regime", "timepoint")
                if scalar(raw_context.get(key))
            }
            if context:
                chain["context"] = context
        for key in (
            "relation",
            "outcome_relation",
            "polarity",
            "modality",
            "extraction_method",
            "direct_relation",
            "causal_claim",
            "trigger_location",
            "outcome_location",
        ):
            value = raw_chain.get(key)
            if isinstance(value, dict):
                chain[key] = dict(value)
            elif isinstance(value, bool):
                chain[key] = value
            elif scalar(value):
                chain[key] = scalar(value)
        entities = raw_chain.get("entities")
        if isinstance(entities, list):
            chain["entities"] = [item for item in entities if isinstance(item, dict) or scalar(item)]
        evidence_edges = raw_chain.get("evidence_edges")
        if isinstance(evidence_edges, list):
            chain["evidence_edges"] = [dict(item) for item in evidence_edges if isinstance(item, dict)]
        chains.append(chain)
    return chains

