"""LLM-primary coherence audit for research-question contracts."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

try:
    from ._research_question_contract import validate_research_question_contract
    from ._science_execution_policy import ScienceExecutionPolicy
except ImportError:
    from _research_question_contract import validate_research_question_contract
    from _science_execution_policy import ScienceExecutionPolicy


CONTRACT_COHERENCE_SCHEMA_VERSION = "research_contract_coherence_v2"
CONTRACT_COHERENCE_PROMPT_REVISION = "research_contract_coherence_v2_0"
CONTRACT_COHERENCE_MAX_LLM_ATTEMPTS = 2
COHERENCE_ISSUE_CODES = frozenset({
    "RESEARCH_OBJECTS_NOT_COMPARABLE",
    "ENDPOINTS_INCOMPATIBLE",
    "TEMPORAL_SCALE_INCOMPATIBLE",
    "SPATIAL_SCALE_INCOMPATIBLE",
    "TASKS_MIXED",
    "REQUIRED_SLOTS_NOT_JOINTLY_FEASIBLE",
    "QUESTION_KIND_SLOT_MISMATCH",
    "SCOPE_DECLARATION_CONTRADICTORY",
})


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _model_id() -> str:
    try:
        from .config import QWEN_MODEL_ID
    except ImportError:
        from config import QWEN_MODEL_ID
    return str(QWEN_MODEL_ID or "")


def _default_llm_call(**kwargs: Any) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    return call_llm_json(**kwargs)


def _contract_revision(contract: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _text(contract.get("contract_revision") or contract.get("declaration_hash")),
        _text(contract.get("declaration_hash") or contract.get("contract_revision")),
    )


def build_contract_anchor_catalog(contract: Mapping[str, Any]) -> list[dict[str, str]]:
    """Expose stable prompt-local ids for every scalar contract value."""

    catalog: list[dict[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                visit(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")
            return
        normalized = _text(value)
        if not normalized:
            return
        catalog.append({
            "anchor_id": f"A{len(catalog) + 1:03d}",
            "path": path,
            "text": normalized,
        })

    visit(contract, "")
    return catalog


def research_contract_coherence_gate(audit: Any) -> dict[str, Any]:
    """Return the only execution gate used by retrieval and TanXi."""

    source = dict(audit) if isinstance(audit, Mapping) else {}
    status = _text(source.get("status")) or "COHERENCE_AUDIT_REQUIRED"
    retrieval_allowed = (
        status in {"COHERENT", "DETERMINISTIC_DIAGNOSTIC"}
        and source.get("retrieval_allowed") is True
    )
    if retrieval_allowed:
        recovery_action = "continue_contract_scoped_retrieval"
    elif status == "CONTRACT_SCOPE_INCOHERENT":
        recovery_action = "re_decompose_or_narrow_research_question_contract"
    elif status == "COHERENCE_PENDING":
        recovery_action = "resume_contract_coherence_audit"
    else:
        recovery_action = "run_contract_coherence_audit"
    return {
        "schema_version": "research_contract_coherence_execution_gate_v1",
        "status": status,
        "ready": retrieval_allowed,
        "retrieval_allowed": retrieval_allowed,
        "tanxi_allowed": retrieval_allowed,
        "formal_scientific_conclusion_allowed": (
            source.get("formal_scientific_conclusion_allowed") is True
        ),
        "reason_codes": list(source.get("reason_codes") or []),
        "recovery_action": _text(source.get("recovery_action")) or recovery_action,
    }


def _validate_coherence_payload(
    payload: Any,
    anchor_catalog: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    if not isinstance(payload, Mapping):
        return "", [], ["LLM_CONTRACT_COHERENCE_SCHEMA_INVALID"]
    verdict = _text(payload.get("verdict")).upper()
    raw_issues = payload.get("issues")
    if verdict not in {"COHERENT", "INCOHERENT"} or not isinstance(raw_issues, list):
        return verdict, [], ["LLM_CONTRACT_COHERENCE_SCHEMA_INVALID"]
    anchors_by_id = {
        item["anchor_id"]: item
        for item in anchor_catalog
    }
    issues: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    for index, issue in enumerate(raw_issues):
        if not isinstance(issue, Mapping):
            validation_errors.append(f"ISSUE_{index}_NOT_OBJECT")
            continue
        code = _text(issue.get("code")).upper()
        anchor_ids = [
            _text(item) for item in issue.get("contract_anchor_ids", [])
            if _text(item)
        ] if isinstance(issue.get("contract_anchor_ids"), list) else []
        if code not in COHERENCE_ISSUE_CODES:
            validation_errors.append(f"ISSUE_{index}_CODE_INVALID")
        if not anchor_ids or any(anchor_id not in anchors_by_id for anchor_id in anchor_ids):
            validation_errors.append(f"ISSUE_{index}_ANCHOR_ID_INVALID")
        resolved_anchors = [
            anchors_by_id[anchor_id]
            for anchor_id in anchor_ids
            if anchor_id in anchors_by_id
        ]
        issues.append({
            "code": code,
            "explanation": _text(issue.get("explanation")),
            "contract_anchor_ids": anchor_ids,
            "contract_anchor_paths": [item["path"] for item in resolved_anchors],
            "contract_anchor_texts": [item["text"] for item in resolved_anchors],
        })
    if verdict == "COHERENT" and issues:
        validation_errors.append("COHERENT_VERDICT_CONTAINS_ISSUES")
    if verdict == "INCOHERENT" and not issues:
        validation_errors.append("INCOHERENT_VERDICT_REQUIRES_ISSUE")
    return verdict, issues, sorted(set(validation_errors))


def _cached_audit(
    existing: Any,
    contract: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
) -> dict[str, Any] | None:
    if not isinstance(existing, Mapping):
        return None
    revision, declaration_hash = _contract_revision(contract)
    if any((
        _text(existing.get("schema_version")) != CONTRACT_COHERENCE_SCHEMA_VERSION,
        _text(existing.get("status")) not in {"COHERENT", "CONTRACT_SCOPE_INCOHERENT"},
        _text(existing.get("contract_id")) != _text(contract.get("contract_id")),
        _text(existing.get("contract_revision")) != revision,
        _text(existing.get("contract_hash")) != declaration_hash,
        _text(existing.get("prompt_revision")) != CONTRACT_COHERENCE_PROMPT_REVISION,
        _text(existing.get("model_id")) != _model_id(),
        dict(existing.get("effective_policy") or {}) != policy.to_dict(),
    )):
        return None
    cached = dict(existing)
    cached["cache_status"] = "HIT"
    return cached


def audit_research_question_contract(
    contract: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validated = validate_research_question_contract(dict(contract))
    cached = _cached_audit(existing, validated, policy)
    if cached is not None:
        return cached
    contract_id = _text(validated.get("contract_id"))
    revision, declaration_hash = _contract_revision(validated)
    provenance = {
        "schema_version": CONTRACT_COHERENCE_SCHEMA_VERSION,
        "contract_id": contract_id,
        "contract_revision": revision,
        "contract_hash": declaration_hash,
        "prompt_revision": CONTRACT_COHERENCE_PROMPT_REVISION,
        "model_id": _model_id(),
        "effective_policy": policy.to_dict(),
        "cache_status": "MISS",
    }
    if not policy.use_llm or policy.decomposition_mode != "llm_primary":
        return {
            **provenance,
            "status": "DETERMINISTIC_DIAGNOSTIC",
            "verdict": "NOT_EVALUATED",
            "issues": [],
            "reason_codes": ["LLM_CONTRACT_COHERENCE_DISABLED"],
            "retrieval_allowed": True,
            "formal_scientific_conclusion_allowed": False,
            "recovery_action": "run_contract_coherence_audit_before_formal_conclusion",
        }
    anchor_catalog = build_contract_anchor_catalog(validated)
    base_prompt = (
        "Audit whether this research-question contract is internally coherent before retrieval. "
        "Assess research-object comparability, endpoint compatibility, temporal and spatial scales, "
        "task consistency, joint feasibility of required evidence slots, and question-kind/slot consistency. "
        "Use only the supplied contract. Every issue must cite one or more contract_anchor_ids from "
        "the supplied anchor catalog; never construct an anchor, path, or quotation yourself. "
        "Return exactly {\"verdict\":\"COHERENT|INCOHERENT\",\"issues\":[{\"code\":...,"
        "\"explanation\":...,\"contract_anchor_ids\":[\"A001\"]}]}.\n"
        f"Allowed issue codes: {json.dumps(sorted(COHERENCE_ISSUE_CODES))}\n"
        f"Contract anchor catalog: {json.dumps(anchor_catalog, ensure_ascii=False)}\n"
        f"Contract: {json.dumps(validated, ensure_ascii=False)}"
    )
    call = llm_call or _default_llm_call
    attempt_errors: list[str] = []
    last_issues: list[dict[str, Any]] = []
    for attempt in range(1, CONTRACT_COHERENCE_MAX_LLM_ATTEMPTS + 1):
        retry_instruction = (
            "\nYour previous response failed this protocol: "
            + ", ".join(attempt_errors[-1:])
            + ". Return a complete JSON object using only declared contract_anchor_ids."
            if attempt_errors else ""
        )
        try:
            payload = call(
                system=(
                    "You audit research-contract coherence. Return JSON only. Do not use external facts, "
                    "domain stereotypes, or unstated assumptions."
                ),
                prompt=base_prompt + retry_instruction,
                max_tokens=2200,
            )
        except Exception as exc:
            attempt_errors.append(
                f"LLM_CONTRACT_COHERENCE_FAILED:{type(exc).__name__}"
            )
            continue
        verdict, issues, validation_errors = _validate_coherence_payload(
            payload,
            anchor_catalog,
        )
        last_issues = issues
        if validation_errors:
            attempt_errors.append("|".join(validation_errors))
            continue
        incoherent = verdict == "INCOHERENT"
        return {
            **provenance,
            "status": "CONTRACT_SCOPE_INCOHERENT" if incoherent else "COHERENT",
            "verdict": verdict,
            "issues": issues,
            "reason_codes": sorted({item["code"] for item in issues}),
            "retrieval_allowed": not incoherent,
            "formal_scientific_conclusion_allowed": not incoherent,
            "recovery_action": (
                "re_decompose_or_narrow_research_question_contract"
                if incoherent else "continue_contract_scoped_retrieval"
            ),
            "llm_attempt_count": attempt,
        }
    reason_codes = sorted({
        code
        for attempt_error in attempt_errors
        for code in attempt_error.split("|")
        if code
    })
    return {
        **provenance,
        "status": "COHERENCE_PENDING",
        "verdict": "PENDING",
        "issues": last_issues,
        "reason_codes": reason_codes or ["LLM_CONTRACT_COHERENCE_FAILED"],
        "retrieval_allowed": False,
        "formal_scientific_conclusion_allowed": False,
        "recovery_action": "resume_contract_coherence_audit",
        "llm_attempt_count": CONTRACT_COHERENCE_MAX_LLM_ATTEMPTS,
        "attempt_errors": attempt_errors,
    }
