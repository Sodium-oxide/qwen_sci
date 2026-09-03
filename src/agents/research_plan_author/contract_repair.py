"""One constrained repair path for malformed Author LLM JSON contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import json
import re
from typing import Any

from .llm_json import call_required_json


AUTHOR_CONTRACT_REPAIR_AUDIT_SCHEMA_VERSION = "research_plan_author_contract_repair_audit_v1"
class AuthorContractRepairError(RuntimeError):
    """Carries a private artifact audit when a single permitted repair fails."""

    def __init__(self, message: str, *, audit: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.audit = deepcopy(dict(audit))


def _contains_forbidden_reference(value: object) -> bool:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value or "")
    return bool(re.search(r"\b(?:doi|https?://|arxiv:|pmid)\b", text, flags=re.IGNORECASE))


def validate_author_contract_repair(
    initial: Mapping[str, Any],
    repaired: Mapping[str, Any],
) -> list[str]:
    """Reject unsafe new bibliographic identifiers while allowing source-bounded prose repairs."""

    errors: list[str] = []
    if _contains_forbidden_reference(repaired) and not _contains_forbidden_reference(initial):
        errors.append("contract repair introduced a bibliographic identifier or URL")
    return errors


def build_author_contract_repair_prompt(
    *,
    artifact_kind: str,
    initial_candidate: Mapping[str, Any],
    validation_errors: list[str],
    allowed_structural_strings: set[str],
    contract_schema: Mapping[str, Any] | None = None,
) -> str:
    """Tell the LLM exactly what contract repair may and may not do."""

    payload = {
        "artifact_kind": artifact_kind,
        "target_contract_schema": deepcopy(dict(contract_schema)) if isinstance(contract_schema, Mapping) else {},
        "initial_candidate": dict(initial_candidate),
        "validation_errors": list(validation_errors),
        "allowed_structural_strings": sorted(allowed_structural_strings),
    }
    instructions = """You are performing one constrained JSON contract repair for a research-plan authoring stage. Return exactly one repaired artifact object and nothing else.

The `target_contract_schema` is the output contract. Your response must be the artifact described by that schema, not the INPUT_JSON envelope. Never return `artifact_kind`, `target_contract_schema`, `initial_candidate`, `validation_errors`, or `allowed_structural_strings` as top-level output fields unless the target schema explicitly requires them.

You may correct required fields, enum values, IDs, references, route membership, duplicate identifiers, and source-bounded prose. You must not add literature, citations, DOI, URLs, author names, numerical values, methods, sample sizes, instruments, definitions, lemmas, results, observations, proof claims, counterexamples, or verification claims that are absent from the supplied context. Do not upgrade a proposed or unverified statement. If an error cannot be fixed under these constraints, preserve the relevant value and let validation fail.

INPUT_JSON:
"""
    return instructions + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def repair_once(
    *,
    artifact_kind: str,
    initial_candidate: Mapping[str, Any],
    validation_errors: list[str],
    llm_call: Callable[..., object] | None,
    validate: Callable[[Mapping[str, Any]], list[str]],
    allowed_structural_strings: set[str] | None = None,
    contract_schema: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attempt precisely one repair; raw candidates stay in the returned audit only."""

    allowed = set(allowed_structural_strings or set())
    audit: dict[str, Any] = {
        "schema_version": AUTHOR_CONTRACT_REPAIR_AUDIT_SCHEMA_VERSION,
        "artifact_kind": artifact_kind,
        "repair_attempted": True,
        "initial_candidate": deepcopy(dict(initial_candidate)),
        "initial_validation_errors": list(validation_errors),
        "repair_status": "PENDING",
        "repair_validation_errors": [],
        "constraints": [
            "Only JSON structure, enum values, IDs, references, and source-bounded prose may be repaired.",
            "No facts, sources, citations, DOI, numerical values, methods, results, proof claims, or verification claims may be added.",
        ],
    }
    try:
        repaired = call_required_json(
            llm_call,
            build_author_contract_repair_prompt(
                artifact_kind=artifact_kind,
                initial_candidate=initial_candidate,
                validation_errors=validation_errors,
                allowed_structural_strings=allowed,
                contract_schema=contract_schema,
            ),
            stage=f"{artifact_kind}_contract_repair",
        )
    except Exception as error:
        audit["repair_status"] = "LLM_FAILURE"
        audit["repair_error"] = f"{type(error).__name__}: {error}"
        raise AuthorContractRepairError(f"{artifact_kind}: constrained contract repair failed", audit=audit) from error
    repair_errors = validate_author_contract_repair(initial_candidate, repaired)
    repair_errors.extend(validate(repaired))
    if repair_errors:
        audit["repair_status"] = "REJECTED"
        audit["repair_validation_errors"] = sorted(set(repair_errors))
        audit["repaired_candidate"] = deepcopy(repaired)
        raise AuthorContractRepairError(
            f"{artifact_kind}: constrained repair produced an invalid JSON contract: " + "; ".join(sorted(set(repair_errors))),
            audit=audit,
        )
    audit["repair_status"] = "REPAIRED"
    audit["repaired_candidate"] = deepcopy(repaired)
    return repaired, audit


__all__ = [
    "AUTHOR_CONTRACT_REPAIR_AUDIT_SCHEMA_VERSION",
    "AuthorContractRepairError",
    "build_author_contract_repair_prompt",
    "repair_once",
    "validate_author_contract_repair",
]
