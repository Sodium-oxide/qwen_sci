from __future__ import annotations

import json
import re
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

try:
    from .config import (
        PACKAGE_DIR,
        SCIENCE_DIR,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE,
        FULLTEXT_PREPARE_BATCH_SIZE,
    )
    from ._debate import QWEN_RESEARCH_ROLE_MODELS
    from .log import log_event
except ImportError:
    from config import (
        PACKAGE_DIR,
        SCIENCE_DIR,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE,
        FULLTEXT_PREPARE_BATCH_SIZE,
    )
    from _debate import QWEN_RESEARCH_ROLE_MODELS
    from log import log_event


AUTOGEN_DIR = SCIENCE_DIR / "autogen_groupchats"
AUTOGEN_RUN_DIR = SCIENCE_DIR / "autogen_runs"
LEGACY_AUTOGEN_DIR = PACKAGE_DIR / ".science" / "autogen_groupchats"
LEGACY_AUTOGEN_RUN_DIR = PACKAGE_DIR / ".science" / "autogen_runs"

DEFAULT_AUTOGEN_AGENTS = ["boxue", "zhizhi", "tanxi", "socrates", "mingli", "yanzhen", "duzhi", "bianlun"]

AUTOGEN_RUN_SUMMARY_SCHEMA_VERSION = "autogen_run_summary_v1"
# Tool results are injected into the coordinator model context.  Keep this a
# byte limit (rather than a character limit) so non-ASCII scientific text
# cannot silently exceed the intended context budget.
MAX_AUTOGEN_TOOL_OUTPUT_BYTES = 100_000
AUTOGEN_RUN_SUMMARY_FIELDS = {
    "schema_version",
    "project_id",
    "run_id",
    "groupchat_id",
    "state_version",
    "state_store_id",
    "final_decision",
    "stop_reason",
    "socrates_status",
    "ready_gap_ids",
    "final_hypothesis_id",
    "final_proposal_id",
    "proposal_status",
    "debate_iterations",
    "hypothesis_package_gate",
    "uncovered_analysis_roles",
    "current_allowed_conclusion_strength",
    "checkpoint",
    "resumed_from_run_id",
    "v3_redecomposition_applied",
    "subhypothesis_retrieval_execution_order",
    "research_contract_coherence_recovery",
    "gap_resolution_retrieval_pending",
    "tanxi_candidate_funnel",
    "gap_landscape",
    "blocked_source_grounded_seeds",
    "final_report_ref",
    "run_detail_ref",
    "run_summary_ref",
}


# A checkpoint can describe a task as completed only when it achieved a V3
# coverage-success terminal state. A completed comparison diagnostic is also
# reusable: it records failed bundle formation, not scientific coverage.
# Provider failures remain resumable work; recording them as completed would
# silently suppress a necessary retry.
_V3_RETRIEVAL_CHECKPOINT_SUCCESS_STATUSES = frozenset(
    {
        "DIRECT_SLOT_ADMITTED",
        "REUSED_EXISTING_EVIDENCE",
        "REUSED_PRIOR_V3_TASK_OUTCOME",
        "REUSED_SHARED_FOUNDATIONAL_CONTEXT",
        "COMPARISON_EVIDENCE_INCONCLUSIVE",
    }
)


def v3_retrieval_task_checkpoint_reusable(row: dict[str, Any]) -> bool:
    """Return whether one V3 retrieval task is safely reusable from checkpoint.

    An execution-order record without an explicit terminal status is not proof
    of completion.  In particular, ``SEARCH_ERROR``,
    ``QUERY_PLAN_CONTRACT_ERROR`` and ``QUERY_COMPILATION_REPAIR_REQUIRED``
    are resumable work, never completed evidence coverage.
    """

    if not isinstance(row, dict) or not str(row.get("task_id") or "").strip():
        return False
    return str(row.get("status") or "").upper() in (
        _V3_RETRIEVAL_CHECKPOINT_SUCCESS_STATUSES
    )


def v3_checkpoint_retrieval_task_ids(
    execution_order: dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    """Split current V3 retrieval entries into reusable and resumable task ids."""

    scheduled_entries = (
        execution_order.get("entries")
        if isinstance(execution_order, dict)
        and isinstance(execution_order.get("entries"), list)
        else []
    )
    reused_entries = (
        execution_order.get("reused_completed_task_rows")
        if isinstance(execution_order, dict)
        and isinstance(execution_order.get("reused_completed_task_rows"), list)
        else []
    )
    reusable: list[str] = []
    resumable: list[str] = []
    for row in [*scheduled_entries, *reused_entries]:
        if not isinstance(row, dict) or str(row.get("revision_of_task_id") or ""):
            continue
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            continue
        target = reusable if v3_retrieval_task_checkpoint_reusable(row) else resumable
        if task_id not in target:
            target.append(task_id)
    return reusable, resumable


_V3_GAP_RESOLUTION_COMPLETION_STATUSES = frozenset({
    "QUALIFICATION_COMPLETED",
    "DIRECTLY_RESOLVED",
})


def v3_gap_resolution_retrieval_pending_summary(
    work_items: list[dict[str, Any]] | None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project the resumable GAP_RESOLUTION queue for GroupChat state.

    This is workflow reporting only.  It does not infer scientific coverage
    from a provider error, an empty metadata result, or an incomplete
    acquisition stage.
    """

    pending: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for raw in work_items or []:
        item = raw if isinstance(raw, dict) else {}
        if (
            str(item.get("schema_version") or "") != "retrieval_work_item_v3"
            or str(item.get("work_item_kind") or "") != "GAP_RESOLUTION"
        ):
            continue
        execution = item.get("execution_state") if isinstance(item.get("execution_state"), dict) else {}
        status = str(execution.get("status") or "PENDING").upper()
        if status in _V3_GAP_RESOLUTION_COMPLETION_STATUSES:
            continue
        candidate_identity = str(item.get("gap_candidate_id") or "")
        if candidate_identity:
            seen_candidate_ids.add(candidate_identity)
        pending.append({
            "work_item_id": str(item.get("work_item_id") or ""),
            "candidate_identity": candidate_identity,
            "gap_candidate_fingerprint": str(item.get("gap_candidate_fingerprint") or ""),
            "target_slot_ids": list(item.get("target_slot_ids") or []),
            "missing_obligation_slot_ids": list(
                execution.get("missing_obligation_slot_ids")
                or item.get("target_slot_ids")
                or []
            ),
            "status": status,
            "stage": str(execution.get("stage") or "QUERY_COMPILATION"),
            "reason_code": str(
                execution.get("reason_code")
                or "GAP_RESOLUTION_EVIDENCE_ACQUISITION_INCOMPLETE"
            ),
            "provider_outcomes": [
                dict(outcome)
                for outcome in execution.get("provider_outcomes", [])
                if isinstance(outcome, dict)
            ],
        })
    for raw in candidates or []:
        candidate = raw if isinstance(raw, dict) else {}
        assessment = candidate.get("gap_assessment") if isinstance(candidate.get("gap_assessment"), dict) else {}
        if str(assessment.get("route") or "") != "TARGETED_RETRIEVAL":
            continue
        candidate_identity = str(candidate.get("candidate_identity") or "")
        if candidate_identity in seen_candidate_ids:
            continue
        retrieval = (
            candidate.get("gap_resolution_retrieval")
            if isinstance(candidate.get("gap_resolution_retrieval"), dict)
            else {}
        )
        pending.append({
            "work_item_id": str(retrieval.get("work_item_id") or ""),
            "candidate_identity": candidate_identity,
            "gap_candidate_fingerprint": str(retrieval.get("gap_candidate_fingerprint") or ""),
            "target_slot_ids": list(retrieval.get("target_slot_ids") or []),
            "missing_obligation_slot_ids": list(retrieval.get("missing_obligation_slot_ids") or []),
            "status": str(retrieval.get("status") or "PENDING_SLOT_BINDING").upper(),
            "stage": str(retrieval.get("stage") or "CONTRACT_VALIDATION"),
            "reason_code": str(
                retrieval.get("reason_code") or "GAP_RESOLUTION_SLOT_BINDING_REQUIRED"
            ),
            "provider_outcomes": [],
        })
    return {
        "schema_version": "autogen_gap_resolution_pending_v3",
        "pending": bool(pending),
        "items": pending,
    }


def autogen_primary_package_socrates_admission(
    candidate: dict[str, Any],
    research_packages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate the closed V3 admission contract for a Socrates review.

    This is intentionally a verifier, never a compatibility adapter: old
    candidate states, old retrieval assessments, and unqualified packages do
    not receive an inferred route to Socrates.
    """

    item = candidate if isinstance(candidate, dict) else {}
    assessment = item.get("gap_assessment") if isinstance(item.get("gap_assessment"), dict) else {}
    semantic = item.get("semantic_audit") if isinstance(item.get("semantic_audit"), dict) else {}
    retrieval = item.get("retrieval_assessment") if isinstance(item.get("retrieval_assessment"), dict) else {}
    rebind = item.get("retrieval_rebind") if isinstance(item.get("retrieval_rebind"), dict) else {}
    span_gate = item.get("primary_source_span_gate") if isinstance(item.get("primary_source_span_gate"), dict) else {}
    gap_id = str(item.get("gap_id") or "")
    reasons: list[str] = []
    if item.get("schema_version") != "gap_candidate_v2" or assessment.get("schema_version") != "gap_assessment_v2":
        reasons.append("CURRENT_V3_CANDIDATE_ASSESSMENT_REQUIRED")
    if assessment.get("candidate_stage") != "QUALIFIED":
        reasons.append("CANDIDATE_QUALIFICATION_REQUIRED")
    if assessment.get("route") != "PRIMARY_CANDIDATE":
        reasons.append("PRIMARY_ROUTE_REQUIRED")
    if assessment.get("semantic_verdict") != "ENTAILED":
        reasons.append("SEMANTIC_ENTAILMENT_REQUIRED")
    if assessment.get("scope_status") != "CORE_DIRECT":
        reasons.append("CORE_DIRECT_SCOPE_REQUIRED")
    if assessment.get("evidence_maturity") != "DESIGN_READY":
        reasons.append("DESIGN_READY_EVIDENCE_REQUIRED")
    if span_gate.get("schema_version") != "primary_source_span_gate_v3" or span_gate.get("status") != "PASSED":
        reasons.append("PRIMARY_SOURCE_SPAN_GATE_REQUIRED")
    if semantic.get("schema_version") != "gap_semantic_audit_result_v3":
        reasons.append("CURRENT_V3_SEMANTIC_AUDIT_REQUIRED")
    if retrieval.get("schema_version") != "gap_retrieval_assessment_v3":
        reasons.append("CURRENT_V3_RETRIEVAL_ASSESSMENT_REQUIRED")
    if rebind.get("schema_version") != "gap_retrieval_evidence_rebind_v3":
        reasons.append("V3_RETRIEVAL_EVIDENCE_REBIND_REQUIRED")
    if str(retrieval.get("rebind_fingerprint") or "") != str(rebind.get("rebind_fingerprint") or ""):
        reasons.append("RETRIEVAL_REBIND_FINGERPRINT_MISMATCH")
    if int(semantic.get("assessment_version") or -1) != int(item.get("assessment_version") or 0):
        reasons.append("SEMANTIC_AUDIT_NOT_CURRENT")
    matching_packages = [
        package for package in research_packages
        if isinstance(package, dict)
        and str(package.get("gap_id") or "") == gap_id
        and str(package.get("research_package_id") or "")
    ]
    if not matching_packages:
        reasons.append("CURRENT_PRIMARY_RESEARCH_PACKAGE_REQUIRED")
    return {
        "schema_version": "autogen_socrates_admission_v3",
        "gap_id": gap_id,
        "candidate_identity": str(item.get("candidate_identity") or ""),
        "allowed": not reasons,
        "reason_codes": reasons,
        "research_package_ids": [str(package.get("research_package_id") or "") for package in matching_packages],
    }


def autogen_science_dir() -> Path:
    """Return the same live science root used by the project store.

    Migration and isolated-run harnesses may rebind ``_project.SCIENCE_DIR``
    after this module has been imported.  Module-level AutoGen paths would
    then write orchestration artifacts to the old root while every specialist
    reads and writes the migrated project.  Resolve through ``projects_dir``
    at the point of use so one GroupChat run has a single state owner.
    """
    try:
        from ._project import projects_dir
    except ImportError:
        from _project import projects_dir
    return projects_dir().parent.resolve()


def autogen_groupchat_dir() -> Path:
    return autogen_science_dir() / "autogen_groupchats"


def autogen_run_dir() -> Path:
    return autogen_science_dir() / "autogen_runs"


def autogen_run_summary_path(run_id: str) -> Path:
    return autogen_run_dir() / f"{run_id}.summary.json"


def existing_autogen_path(
    primary_dir: Path,
    legacy_dir: Path,
    record_id: str,
    additional_dirs: list[Path] | None = None,
) -> Path:
    primary = primary_dir / f"{record_id}.json"
    if primary.exists():
        return primary
    seen = {str(primary_dir.resolve())}
    for directory in [legacy_dir, *(additional_dirs or [])]:
        resolved = str(directory.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        candidate = directory / f"{record_id}.json"
        if candidate.exists():
            return candidate
    return primary


def latest_groupchat_checkpoint(
    *,
    project_id: str,
    groupchat_id: str,
) -> dict[str, Any] | None:
    """Return the latest recoverable V2 run for one project/GroupChat.

    Run artifacts are append-only, so recovery selects by project and, when
    supplied, GroupChat identity.  A retry that only has the project id may
    reattach the most recent interrupted GroupChat instead of creating an
    unrelated orchestration history.
    Malformed historical artifacts are ignored: they remain auditable on disk
    but cannot poison a new GroupChat invocation.
    """

    records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for directory in (autogen_run_dir(), AUTOGEN_RUN_DIR, LEGACY_AUTOGEN_RUN_DIR):
        try:
            resolved = str(directory.resolve())
        except OSError:
            resolved = str(directory)
        if resolved in seen_paths or not directory.exists():
            continue
        seen_paths.add(resolved)
        for path in directory.glob("agr_*.json"):
            try:
                payload = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                records.append(payload)

    # A successful downstream continuation consumes the failed checkpoint it
    # resumed.  Run artifacts are immutable, so derive that fact from their
    # explicit lineage instead of rewriting historical error records.
    consumed_checkpoint_run_ids = {
        str((payload.get("state") or {}).get("resumed_from_run_id") or "")
        for payload in records
        if isinstance(payload.get("state"), dict)
        and str(((payload.get("state") or {}).get("checkpoint") or {}).get("status") or "")
        == "RESUMED_COMPLETED"
        and str((payload.get("state") or {}).get("resumed_from_run_id") or "")
    }
    candidates: list[tuple[float, dict[str, Any]]] = []
    for payload in records:
        if str(payload.get("run_id") or "") in consumed_checkpoint_run_ids:
            continue
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        checkpoint = state.get("checkpoint") if isinstance(state.get("checkpoint"), dict) else {}
        if (
            str(payload.get("project_id") or "") != project_id
            or (groupchat_id and str(payload.get("groupchat_id") or "") != groupchat_id)
            or str(state.get("final_decision") or "") != "checkpointed_error"
            or str(checkpoint.get("status") or "") != "CHECKPOINTED_ERROR"
        ):
            continue
        candidates.append((float(payload.get("createdAt") or 0), payload))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def v3_contract_binding_state(
    record: dict[str, Any],
    contract: dict[str, Any],
    research_question_task_id: str,
) -> dict[str, Any]:
    """Return one document's explicit, contract-scoped V4 admission facts.

    Paper metadata is shared, but alignment, full-text structuring and source
    admission are evaluated relative to a research-question contract.  This
    helper deliberately refuses scalar record-level alignment for multi-SH
    orchestration: treating it as shared would let one branch's decision
    qualify a different branch's retrieval slot.
    """

    record = record if isinstance(record, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    contract_id = str(contract.get("contract_id") or "")
    task_id = str(research_question_task_id or "").strip()
    contract_revision = str(
        contract.get("contract_revision") or contract.get("declaration_hash") or ""
    )
    contract_hash = str(
        contract.get("declaration_hash") or contract.get("contract_revision") or ""
    )
    sub_hypothesis_id = str(contract.get("sub_hypothesis_id") or "")
    bindings = (
        record.get("subhypothesis_bindings")
        if isinstance(record.get("subhypothesis_bindings"), list)
        else []
    )
    binding = next(
        (
            item
            for item in bindings
            if isinstance(item, dict)
            and str(item.get("research_question_contract_id") or "") == contract_id
            and str(item.get("research_question_contract_revision") or "")
            == contract_revision
            and str(item.get("research_question_contract_hash") or "")
            == contract_hash
            and str(item.get("research_question_task_id") or "") == task_id
        ),
        {},
    )
    binding = binding if isinstance(binding, dict) else {}
    admissions = (
        record.get("gap_source_admissions_v4")
        if isinstance(record.get("gap_source_admissions_v4"), dict)
        else {}
    )
    alignment = binding.get("alignment_assessment")
    structuring = binding.get("fulltext_structuring")
    alignment_indexes = (
        record.get("contract_alignment_artifacts")
        if isinstance(record.get("contract_alignment_artifacts"), dict)
        else {}
    )
    alignment_index = alignment_indexes.get(contract_id)
    task_alignments = (
        alignment_index.get("task_alignments")
        if isinstance(alignment_index, dict)
        and alignment_index.get("schema_version") == "contract_task_alignment_index_v1"
        else {}
    )
    task_alignment = (
        task_alignments.get(task_id) if isinstance(task_alignments, dict) else {}
    )
    if not isinstance(task_alignment, dict):
        task_alignment = {}
    contract_admission = admissions.get(contract_id)
    task_admissions = (
        contract_admission.get("task_admissions")
        if isinstance(contract_admission, dict)
        else {}
    )
    admission = task_admissions.get(task_id) if isinstance(task_admissions, dict) else {}
    if isinstance(admission, dict) and (
        str(admission.get("research_question_contract_revision") or "")
        != contract_revision
        or str(admission.get("research_question_contract_hash") or "")
        != contract_hash
    ):
        admission = {}
    corpus_admitted = admission.get("corpus_admitted") if isinstance(admission, dict) else None
    counts_toward_gate = admission.get("counts_toward_gate") if isinstance(admission, dict) else None
    evidence_kind = str(
        binding.get("evidence_kind")
        or record.get("evidence_kind")
        or (record.get("import_context") or {}).get("evidence_kind")
        or ""
    ).lower()
    return {
        "binding": dict(binding),
        "alignment": dict(alignment) if isinstance(alignment, dict) else {},
        "task_alignment": dict(task_alignment),
        "fulltext_structuring": (
            dict(structuring) if isinstance(structuring, dict) else {}
        ),
        "admission": dict(admission) if isinstance(admission, dict) else {},
        "task_admission_found": isinstance(admission, dict) and bool(admission),
        "corpus_admitted": corpus_admitted,
        "counts_toward_gate": counts_toward_gate,
        "evidence_kind": evidence_kind,
    }


def is_reusable_direct_slot_assertion(
    assertion: dict[str, Any],
    record: dict[str, Any],
    target_contract: dict[str, Any],
    target_task_id: str,
    target_slot: str,
) -> bool:
    """Return whether one assertion may fill one current task slot.

    Foundation rationale, background documents, incomplete full-text imports,
    and artifacts bound to a different contract are intentionally excluded.
    This centralizes the direct-slot predicate so initial reuse and newly
    imported evidence cannot drift into different admission policies.
    """

    assertion = assertion if isinstance(assertion, dict) else {}
    target_contract = target_contract if isinstance(target_contract, dict) else {}
    slot = str(target_slot or "").strip()
    task_id = str(target_task_id or "").strip()
    contract_id = str(target_contract.get("contract_id") or "")
    if (
        not slot
        or not task_id
        or not contract_id
        or str(assertion.get("research_question_contract_id") or "") != contract_id
        or str(assertion.get("research_question_contract_revision") or "")
        != str(
            target_contract.get("contract_revision")
            or target_contract.get("declaration_hash")
            or ""
        )
        or str(assertion.get("research_question_contract_hash") or "")
        != str(
            target_contract.get("declaration_hash")
            or target_contract.get("contract_revision")
            or ""
        )
        or not str(assertion.get("assertion_id") or "")
        or not str(assertion.get("document_version_hash") or "")
        or not list(assertion.get("source_span_ids") or [])
    ):
        return False
    admitted_slot_support = next(
        (
            item
            for item in assertion.get("slot_support", [])
            if isinstance(item, dict)
            and str(item.get("slot_id") or "") == slot
            and str(item.get("research_question_task_id") or "") == task_id
            and str(item.get("support_status") or "") == "VERIFIED_NONCOUNTING"
            and str(item.get("alignment_verdict") or "")
            in {"SUPPORTS", "CONSISTENT_WITH"}
            and str(item.get("assertion_id") or assertion.get("assertion_id") or "")
            == str(assertion.get("assertion_id") or "")
            and set(str(value) for value in item.get("source_span_ids", []) if str(value))
            == set(str(value) for value in assertion.get("source_span_ids", []) if str(value))
        ),
        None,
    )
    if not isinstance(admitted_slot_support, dict):
        return False
    assertion_task_id = str(assertion.get("research_question_task_id") or "").strip()
    if assertion_task_id != task_id:
        return False
    contract_state = v3_contract_binding_state(
        record, target_contract, task_id
    )
    admission = contract_state["admission"]
    evidence_kind = str(contract_state["evidence_kind"] or "").lower()
    support_id = str(admitted_slot_support.get("slot_support_id") or "")
    return bool(
        evidence_kind != "foundational_context"
        and assertion.get("schema_version") == "evidence_assertion_v4"
        and assertion.get("validator_verdict") == "VERIFIED_SOURCE_BOUND"
        and admission.get("admission_level") == "DIRECT_EVIDENCE"
        and admission.get("eligible_for_gap_synthesis") is True
        and admission.get("direct_evidence_eligible") is True
        and str(assertion.get("assertion_id") or "") in set(admission.get("admitted_assertion_ids") or [])
        and support_id in set(admission.get("admitted_slot_support_ids") or [])
    )


def research_question_contract_declaration_summary_v3(
    project: dict[str, Any],
) -> dict[str, Any]:
    """Report whether V3 SH declarations are structurally current.

    This declaration preflight does not authorize retrieval or TanXi. Runtime
    authorization is owned by ``research_question_branch_readiness_summary_v3``.
    """
    try:
        from ._project import DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
        from ._research_question_contract import (
            RESEARCH_QUESTION_CONTRACT_VERSION,
            validate_research_question_contract,
        )
    except ImportError:
        from _project import DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
        from _research_question_contract import (
            RESEARCH_QUESTION_CONTRACT_VERSION,
            validate_research_question_contract,
        )
    ready_ids: list[str] = []
    pending_ids: list[str] = []
    branch_statuses: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(project.get("sub_hypotheses", [])):
        if not isinstance(item, dict):
            continue
        sub_id = str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}").strip()
        if not sub_id:
            continue
        contract = item.get("research_question_contract") if isinstance(item.get("research_question_contract"), dict) else {}
        try:
            valid = (
                contract.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION
                and bool(validate_research_question_contract(contract).get("contract_id"))
                and bool(contract.get("contract_revision") or contract.get("declaration_hash"))
            )
        except (TypeError, ValueError):
            valid = False
        branch_statuses[sub_id] = {
            "ready": valid,
            "status": "READY_FOR_SOURCE_BOUND_GAP_ANALYSIS" if valid else "BLOCKED_V3_RESEARCH_QUESTION_CONTRACT",
            "reason": (
                "Current V3 research-question contract is available; source evidence may now be analysed or its extraction shortage routed to retrieval."
                if valid
                else "A current research_question_contract_v3 with an identity and revision is required before source-bound gap analysis."
            ),
            "research_question_contract_id": str(contract.get("contract_id") or "") if valid else "",
            "research_question_contract_revision": str(contract.get("contract_revision") or contract.get("declaration_hash") or "") if valid else "",
        }
        if valid:
            ready_ids.append(sub_id)
        else:
            pending_ids.append(sub_id)
    decomposition = (
        project.get("objective_decomposition")
        if isinstance(project.get("objective_decomposition"), dict)
        else {}
    )
    if not ready_ids and not pending_ids:
        decomposition_status = str(decomposition.get("status") or "")
        status = (
            decomposition_status
            if decomposition_status in DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
            else "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        )
    elif pending_ids:
        status = "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
    else:
        status = "READY_FOR_SOURCE_BOUND_RETRIEVAL"
    return {
        "schema_version": "research_question_contract_declaration_summary_v3",
        "status": status,
        "total": len(ready_ids) + len(pending_ids),
        "readiness_basis": "CURRENT_RESEARCH_QUESTION_CONTRACT_DECLARATION",
        "legacy_causal_fulltext_gate_used": False,
        "ready_sub_hypothesis_ids": ready_ids,
        "pending_sub_hypothesis_ids": pending_ids,
        "branch_statuses": branch_statuses,
    }


def decomposition_protocol_block_result_v3(
    *,
    project_id: str,
    decomposition: dict[str, Any],
    contract_preflight: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ._project import DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
    except ImportError:
        from _project import DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
    status = str(contract_preflight.get("status") or "")
    if (
        status not in DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
        or contract_preflight.get("ready_sub_hypothesis_ids")
    ):
        return {}
    repair_audit = dict(decomposition.get("candidate_repair_audit") or {})
    stop_reasons = {
        "LLM_DECOMPOSITION_EMPTY": "The bounded V3 generation call returned an explicit empty candidate array after its one complete envelope regeneration.",
        "LLM_DECOMPOSITION_RESPONSE_TRUNCATED": "The V3 decomposition response was truncated; no partial array was accepted as a complete candidate set.",
        "LLM_DECOMPOSITION_ROOT_PROTOCOL_INVALID": "The V3 decomposition response failed the strict root-object protocol after its one complete envelope regeneration.",
        "LLM_DECOMPOSITION_TIMEOUT": "The V3 decomposition LLM call timed out and produced no complete candidate envelope.",
        "LLM_DECOMPOSITION_INVOCATION_FAILED": "The V3 decomposition LLM call failed before a complete candidate envelope was produced.",
        "LLM_DECOMPOSITION_DISABLED": "LLM decomposition is disabled, so no weaker heuristic SH fallback is available.",
        "DECOMPOSITION_CANDIDATE_REPAIR_REQUIRED": "V3 candidates were returned but none passed the discriminated contract protocol; the failure audit requires a protocol-directed correction.",
        "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED": "No V3 candidate passed after the single protocol-directed candidate repair call.",
    }
    return {
        "schema_version": "autogen_decomposition_protocol_block_v3",
        "project_id": project_id,
        "status": status,
        "final_decision": status.lower(),
        "retryable": False,
        "stop_reason": stop_reasons[status],
        "research_question_contract_preflight": contract_preflight,
        "candidate_validation_audit": dict(
            decomposition.get("candidate_validation_audit") or {}
        ),
        "candidate_repair_audit": repair_audit,
        "allowed_next_stages": [
            "inspect_candidate_validation_audit",
            "revise_decomposition_protocol_or_research_scope",
        ],
        "blocked_stages": [
            "run_autogen_groupchat_retry",
            "literature_retrieval",
            "run_tanxi_gap_exploration",
            "run_socrates_type_specific_review",
            "write_research_proposal_v2",
        ],
    }


def research_question_branch_readiness_summary_v3(
    project: dict[str, Any],
) -> dict[str, Any]:
    """Apply the shared coherence gate before retrieval or TanXi."""

    try:
        from ._research_contract_coherence import research_contract_coherence_gate
    except ImportError:
        from _research_contract_coherence import research_contract_coherence_gate
    declarations = research_question_contract_declaration_summary_v3(project)
    audits = (
        project.get("research_contract_coherence_audits_v3")
        if isinstance(project.get("research_contract_coherence_audits_v3"), dict)
        else {}
    )
    ready_ids: list[str] = []
    pending_ids: list[str] = []
    coherence_blocked_ids: list[str] = []
    domain_blocked_ids: list[str] = []
    branch_statuses: dict[str, dict[str, Any]] = {}
    coherence_status_counts: dict[str, int] = {}
    contracts_by_sub_id = {
        str(item.get("id") or item.get("sub_hypothesis_id") or ""): (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
    }
    for sub_id, declaration in declarations["branch_statuses"].items():
        if declaration.get("ready") is not True:
            branch_statuses[sub_id] = dict(declaration)
            pending_ids.append(sub_id)
            continue
        contract = contracts_by_sub_id.get(sub_id) or {}
        domain_contract = (
            contract.get("research_domain_contract")
            if isinstance(contract.get("research_domain_contract"), dict)
            else {}
        )
        domain_ready = bool(
            str(domain_contract.get("status") or "").upper() == "READY"
            and str(domain_contract.get("primary_domain_id") or "").strip()
            and any(str(item).strip() for item in domain_contract.get("active_domain_ids", []))
        )
        if not domain_ready:
            branch_statuses[sub_id] = {
                **dict(declaration),
                "ready": False,
                "status": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
                "reason": (
                    "Retrieval is blocked until the explicit research-domain contract "
                    "has a READY primary and active domain declaration."
                ),
                "research_domain_contract": dict(domain_contract),
                "recovery_action": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
            }
            pending_ids.append(sub_id)
            domain_blocked_ids.append(sub_id)
            continue
        gate = research_contract_coherence_gate(audits.get(sub_id))
        status = str(gate.get("status") or "COHERENCE_AUDIT_REQUIRED")
        coherence_status_counts[status] = coherence_status_counts.get(status, 0) + 1
        ready = gate.get("ready") is True
        branch_statuses[sub_id] = {
            **dict(declaration),
            "ready": ready,
            "status": (
                "READY_FOR_SOURCE_BOUND_GAP_ANALYSIS"
                if ready else f"BLOCKED_{status}"
            ),
            "reason": (
                "The current contract passed the shared coherence gate and may enter retrieval and TanXi."
                if ready
                else "Retrieval and TanXi are both blocked until the contract coherence recovery action completes."
            ),
            "coherence_gate": gate,
        }
        if ready:
            ready_ids.append(sub_id)
        else:
            pending_ids.append(sub_id)
            coherence_blocked_ids.append(sub_id)
    return {
        "schema_version": "research_question_branch_readiness_v4",
        "readiness_basis": "CURRENT_CONTRACT_AND_SHARED_COHERENCE_GATE",
        "legacy_causal_fulltext_gate_used": False,
        "ready_sub_hypothesis_ids": ready_ids,
        "execution_ready_sub_hypothesis_ids": (
            [] if coherence_blocked_ids else ready_ids
        ),
        "coherence_generation_ready": not bool(coherence_blocked_ids),
        "pending_sub_hypothesis_ids": pending_ids,
        "coherence_blocked_sub_hypothesis_ids": coherence_blocked_ids,
        "domain_blocked_sub_hypothesis_ids": domain_blocked_ids,
        "domain_contract_generation_ready": not bool(domain_blocked_ids),
        "coherence_status_counts": coherence_status_counts,
        "branch_statuses": branch_statuses,
    }


def build_research_contract_coherence_recovery_context(
    retrieval_report: dict[str, Any],
) -> dict[str, Any]:
    """Project a blocked retrieval report into a generic decomposition repair brief."""

    blocked_ids = {
        str(item)
        for item in retrieval_report.get("coherence_blocked_sub_hypothesis_ids", [])
        if str(item)
    }
    blocked_contracts: list[dict[str, Any]] = []
    for branch in retrieval_report.get("branches", []):
        if not isinstance(branch, dict):
            continue
        sub_id = str(branch.get("sub_hypothesis_id") or "")
        if sub_id not in blocked_ids:
            continue
        audit = (
            branch.get("contract_coherence_audit")
            if isinstance(branch.get("contract_coherence_audit"), dict)
            else {}
        )
        blocked_contracts.append({
            "sub_hypothesis_id": sub_id,
            "status": str(audit.get("status") or branch.get("status") or ""),
            "reason_codes": list(audit.get("reason_codes") or []),
            "issues": [
                {
                    "code": str(issue.get("code") or ""),
                    "explanation": str(issue.get("explanation") or ""),
                    "contract_anchor_paths": list(
                        issue.get("contract_anchor_paths") or []
                    ),
                    "contract_anchor_texts": list(
                        issue.get("contract_anchor_texts") or []
                    ),
                }
                for issue in audit.get("issues", [])
                if isinstance(issue, dict)
            ],
        })
    return {
        "schema_version": "research_contract_coherence_recovery_context_v1",
        "recovery_kind": str(
            retrieval_report.get("coherence_recovery_kind") or ""
        ),
        "blocked_contracts": blocked_contracts,
        "decomposition_requirements": [
            "replace every rejected scope rather than paraphrasing it",
            "keep each replacement research object internally comparable",
            "keep endpoints and temporal/spatial scales compatible within each contract",
            "separate object-specific contracts from any explicit cross-object synthesis contract",
        ],
    }


def declared_research_question_subhypothesis_ids(project: dict[str, Any]) -> set[str]:
    """Return SHs explicitly declared as V3 before automatic annotation.

    Automatic annotation can construct a V3 contract for a legacy SH, but it
    must not itself switch an existing orchestration run into a new workflow
    without an explicit user/project declaration.  Conversely, once at least
    one current V3 declaration exists, the run is a V3 run and all its SHs
    are reconstructed into the same source-bound pipeline together.
    """
    ids: set[str] = set()
    for index, item in enumerate(project.get("sub_hypotheses", [])):
        if not isinstance(item, dict):
            continue
        is_v3 = (
            isinstance(item.get("research_question"), dict)
            or item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version") == "research_question_contract_v3"
            )
        )
        if is_v3:
            sub_id = str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}").strip()
            if sub_id:
                ids.add(sub_id)
    return ids


def research_question_project_cutover_audit(project: dict[str, Any]) -> dict[str, Any]:
    """Check that one AutoGen run contains only explicit V3 SH contracts.

    AutoGen is an orchestration boundary, not a migration service.  Once an
    SH collection is present, it is either wholly a current
    ResearchQuestionContractV3 decomposition or it must be regenerated.  A
    partial V3 set may not send its remaining legacy branches to the former
    causal retrieval controller.
    """
    try:
        from ._research_question_contract import validate_research_question_contract
    except ImportError:
        from _research_question_contract import validate_research_question_contract
    items = [item for item in project.get("sub_hypotheses", []) if isinstance(item, dict)]
    declared_ids = declared_research_question_subhypothesis_ids(project)
    all_ids = {
        str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}").strip()
        for index, item in enumerate(items)
        if str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}").strip()
    }
    invalid_contract_ids: list[str] = []
    invalid_design_basis_ids: list[str] = []
    design_inventory = (
        project.get("research_design_inventory")
        if isinstance(project.get("research_design_inventory"), dict)
        else {}
    )
    known_design_basis_ids = {
        str(entry.get("id") or "").strip()
        for entry in (design_inventory.get("design_basis") or [])
        if isinstance(entry, dict) and str(entry.get("id") or "").strip()
    }
    for index, item in enumerate(items):
        sub_id = str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}").strip()
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        try:
            current_contract = validate_research_question_contract(contract)
        except (TypeError, ValueError):
            if sub_id:
                invalid_contract_ids.append(sub_id)
            continue
        if not set(current_contract.get("design_basis_ids") or []).issubset(
            known_design_basis_ids
        ):
            if sub_id:
                invalid_design_basis_ids.append(sub_id)
    stale_ids = sorted(
        (all_ids - declared_ids)
        | set(invalid_contract_ids)
        | set(invalid_design_basis_ids)
    )
    return {
        "schema_version": "research_question_project_cutover_audit_v3",
        "status": (
            "CURRENT_V3"
            if declared_ids and not stale_ids
            else "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        ),
        "declared_sub_hypothesis_ids": sorted(declared_ids),
        "stale_sub_hypothesis_ids": stale_ids,
        "invalid_current_v3_contract_ids": sorted(invalid_contract_ids),
        "invalid_design_basis_reference_ids": sorted(invalid_design_basis_ids),
        "research_design_inventory_schema_version": str(
            design_inventory.get("schema_version") or ""
        ),
        "all_subhypotheses_v3": bool(declared_ids and not stale_ids),
        "legacy_causal_artifacts_accepted": False,
    }


def ensure_autogen_project_exists(project_id: str) -> dict[str, Any]:
    normalized = str(project_id or "").strip()
    if not normalized or (normalized.startswith("<") and normalized.endswith(">")):
        raise ValueError(
            f"Cannot create AutoGen GroupChat with unresolved project_id: {normalized or '(empty)'}"
        )
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    return load_project(normalized)


def ensure_groupchat_matches_project(
    groupchat_spec: dict[str, Any],
    project_id: str,
    groupchat_id: str,
) -> None:
    spec_project_id = str(groupchat_spec.get("project_id") or "").strip()
    expected_project_id = str(project_id or "").strip()
    if spec_project_id != expected_project_id:
        raise ValueError(
            "AutoGen GroupChat project mismatch: "
            f"groupchat_id={groupchat_id}, groupchat_project_id={spec_project_id or '(missing)'}, "
            f"requested_project_id={expected_project_id or '(missing)'}. "
            "Create or select a GroupChat belonging to the requested project."
        )
    recorded_science_dir = str(groupchat_spec.get("science_dir") or "").strip()
    active_science_dir = str(autogen_science_dir())
    if recorded_science_dir and Path(recorded_science_dir).resolve() != Path(active_science_dir).resolve():
        raise ValueError(
            "AutoGen GroupChat project-store mismatch: "
            f"groupchat_id={groupchat_id}, groupchat_science_dir={recorded_science_dir}, "
            f"active_science_dir={active_science_dir}. "
            "Create a new GroupChat in the active project store instead of mixing project snapshots."
        )


def create_autogen_groupchat(
    project_id: str,
    goal: str = "",
    agents: list[str] | None = None,
    *,
    max_round: int,
    speaker_selection_method: str,
    human_input_mode: str,
    use_native_autogen: bool,
) -> str:
    ensure_autogen_project_exists(project_id)
    groupchat_id = new_autogen_groupchat_id()
    selected_agents = normalize_agent_list(agents)
    spec = {
        "groupchat_id": groupchat_id,
        "project_id": project_id,
        "science_dir": str(autogen_science_dir()),
        "goal": goal,
        "framework": "autogen_v3_groupchat",
        "native_autogen": native_autogen_status(use_native=use_native_autogen),
        "groupchat": {
            "max_round": clamp_int(max_round, 4, 40),
            "speaker_selection_method": normalize_speaker_selection(speaker_selection_method),
            "allow_repeat_speaker": False,
            "human_input_mode": normalize_human_input_mode(human_input_mode),
            "termination_marker": "TERMINATE",
        },
        "agents": [science_agent_to_autogen_agent(agent) for agent in selected_agents],
        "tools": build_autogen_tool_registry(),
        "round_protocol": build_socratic_groupchat_protocol(),
        "execution_policy": {
            "worktree": "disabled",
            "background_threads": "disabled",
            "state_owner": "groupchat_manager",
            "shared_project_writes": "serialized_by_autogen_flow",
            "token_policy": "structured_turns_not_freeform_chat",
        },
        "createdAt": time.time(),
    }
    save_json(autogen_groupchat_dir() / f"{groupchat_id}.json", spec)
    log_event("AUTOGEN", "groupchat_created", groupchat_id=groupchat_id, project_id=project_id)
    return json.dumps(spec, ensure_ascii=False, indent=2)


def enforce_qwen_model_family(value: str, default: str) -> str:
    """Return an approved Qwen research model or the role default."""

    candidate = str(value or "").strip().lower()
    fallback = str(default or "").strip().lower()
    if fallback not in QWEN_RESEARCH_ROLE_MODELS:
        fallback = "qwen-max"
    return candidate if candidate in QWEN_RESEARCH_ROLE_MODELS else fallback


def v3_research_question_slot_candidate_profile(task: dict[str, Any]) -> dict[str, Any]:
    """Allocate V3 discovery redundancy without lowering evidence admission.

    A profile governs metadata discovery and full-text import attempts. It
    cannot promote a candidate past SourceSpan, explicit assertion, source
    role, or typed-slot requirements.
    """
    task = task if isinstance(task, dict) else {}
    query_mode = str(task.get("query_mode") or "").upper()
    source_role = str(task.get("required_source_role") or "").upper()
    slot = str(task.get("slot") or task.get("evidence_slot") or "").upper()
    requires_dedicated_foundation = bool(
        "FOUNDATION" in source_role or "FOUNDATIONAL" in slot
    )
    if query_mode == "FOUNDATIONAL_CONTEXT":
        return {
            "profile": "v3_foundational_context_redundancy",
            "candidate_budget": 2,
            "layer_quotas": {
                "L3_preprint": 0,
                "L2_top_latest": 0,
                "L0_review": 0,
                "L1_milestone": 0,
                "L4_regular": 0,
            },
            "dedicated_foundation_candidate_target": 2,
            "foundation_lane_status": "V3_FOUNDATIONAL_CONTEXT_WORKFLOW_REQUIRED",
            "admission_policy": (
                "The dedicated V3 foundational-context lane produces rationale candidates only; "
                "it cannot fill direct-primary slots or admit an L1 paper before source-bound context admission."
            ),
        }
    if query_mode == "POSITIVE_EVIDENCE":
        return {
            "profile": "v3_positive_primary_slot_redundancy",
            "candidate_budget": 33,
            "layer_quotas": {
                "L3_preprint": 0,
                "L2_top_latest": 12,
                "L0_review": 3,
                # Broad-pool L1 is forbidden; this zero is intentional.
                "L1_milestone": 0,
                "L4_regular": 18,
            },
            "dedicated_foundation_candidate_target": 2 if requires_dedicated_foundation else 0,
            "foundation_lane_status": (
                "DEDICATED_FOUNDATION_WORKFLOW_REQUIRED"
                if requires_dedicated_foundation
                else "NOT_REQUESTED_BY_V3_TASK"
            ),
            "admission_policy": (
                "Candidate redundancy expands metadata discovery and full-text import attempts only; "
                "SourceSpan, explicit assertion, source-role, and typed evidence-slot gates are unchanged."
            ),
        }
    return {
        "profile": "v3_resolution_slot_bounded",
        "candidate_budget": 12,
        "layer_quotas": {
            "L3_preprint": 0,
            "L2_top_latest": 2,
            "L0_review": 1,
            "L1_milestone": 0,
            "L4_regular": 9,
        },
        "dedicated_foundation_candidate_target": 0,
        "foundation_lane_status": "NOT_APPLICABLE_TO_RESOLUTION_SLOT",
        "admission_policy": (
            "Resolution/disconfirmation retrieval is bounded and cannot use empty coverage as a gap verdict; "
            "all source-bound evidence admission gates remain unchanged."
        ),
    }


def _project_persisted_discipline_taxonomy(project: dict[str, Any]) -> dict[str, Any] | None:
    project = project if isinstance(project, dict) else {}
    direct = project.get("discovery_taxonomy")
    if (
        isinstance(direct, dict)
        and isinstance(direct.get("primary"), dict)
        and str(direct.get("primary", {}).get("key") or "")
        and isinstance(direct.get("provider_filters"), dict)
    ):
        return dict(direct)
    resolution = project.get("domain_resolution")
    nested = resolution.get("discovery_taxonomy") if isinstance(resolution, dict) else None
    if (
        isinstance(nested, dict)
        and isinstance(nested.get("primary"), dict)
        and str(nested.get("primary", {}).get("key") or "")
        and isinstance(nested.get("provider_filters"), dict)
    ):
        restored = dict(nested)
        project["discovery_taxonomy"] = restored
        return restored

    # Older project snapshots can contain the source-grounded identity but an
    # empty taxonomy recorded before the identity-to-catalog bridge existed.
    # Reconstruct only from those persisted project fields, never from the
    # short V3 task query and never through a historical causal contract.
    domain_context = project.get("domain_context") if isinstance(project.get("domain_context"), dict) else {}
    identity = project.get("research_identity") if isinstance(project.get("research_identity"), dict) else {}
    if isinstance(resolution, dict):
        domain_context = resolution.get("domain_context") if isinstance(resolution.get("domain_context"), dict) else domain_context
        identity = resolution.get("research_identity") if isinstance(resolution.get("research_identity"), dict) else identity
    mappings = (
        resolution.get("research_domains")
        if isinstance(resolution, dict) and isinstance(resolution.get("research_domains"), list)
        else project.get("research_domains")
        if isinstance(project.get("research_domains"), list)
        else []
    )
    domain_keys = list(
        dict.fromkeys(
            str(item.get("domain") or "")
            for item in mappings
            if isinstance(item, dict) and str(item.get("domain") or "")
        )
    )
    bridge_terms: list[str] = []
    for value in (
        identity.get("label"),
        domain_context.get("primary"),
        project.get("domain"),
        *(domain_context.get("taxonomy_labels") or []),
        *(domain_context.get("secondary_labels") or []),
        *(domain_context.get("retrieval_terms") or []),
    ):
        term = str(value or "").strip()
        if term and term not in bridge_terms:
            bridge_terms.append(term)
    if not bridge_terms and not domain_keys:
        return None
    try:
        from ._discipline_taxonomy import resolve_discipline_taxonomy
    except ImportError:
        from _discipline_taxonomy import resolve_discipline_taxonomy
    reconciled = resolve_discipline_taxonomy(
        "\n".join(bridge_terms),
        internal_domains=domain_keys,
    )
    reconciled = {
        **reconciled,
        "resolution_source": "v3_project_taxonomy_reconciliation",
        "bridge_terms": bridge_terms,
        "catalog_domain_keys": domain_keys,
    }
    project["discovery_taxonomy"] = reconciled
    if isinstance(resolution, dict):
        resolution["discovery_taxonomy"] = reconciled
    log_event(
        "SCIENCE",
        "v3_project_taxonomy_reconciled",
        project_id=str(project.get("project_id") or ""),
        primary=(reconciled.get("primary") or {}).get("key", ""),
        coverage=reconciled.get("coverage", "unsupported"),
    )
    return reconciled


def _v3_slot_profile_totals(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "task_count": 0,
        "positive_task_count": 0,
        "foundation_context_task_count": 0,
        "resolution_task_count": 0,
        "candidate_budget": 0,
        "L0_review": 0,
        "L2_top_latest": 0,
        "L4_regular": 0,
        "dedicated_foundation_candidate_target": 0,
    }
    for task in tasks:
        profile = v3_research_question_slot_candidate_profile(task)
        quotas = profile.get("layer_quotas") if isinstance(profile.get("layer_quotas"), dict) else {}
        totals["task_count"] += 1
        totals["candidate_budget"] += int(profile.get("candidate_budget") or 0)
        totals["L0_review"] += int(quotas.get("L0_review") or 0)
        totals["L2_top_latest"] += int(quotas.get("L2_top_latest") or 0)
        totals["L4_regular"] += int(quotas.get("L4_regular") or 0)
        totals["dedicated_foundation_candidate_target"] += int(
            profile.get("dedicated_foundation_candidate_target") or 0
        )
        query_mode = str(task.get("query_mode") or "").upper()
        if query_mode == "POSITIVE_EVIDENCE":
            totals["positive_task_count"] += 1
        elif query_mode == "FOUNDATIONAL_CONTEXT":
            totals["foundation_context_task_count"] += 1
        else:
            totals["resolution_task_count"] += 1
    return totals


def v3_objective_decomposition_observability(
    project: dict[str, Any],
    decomposition: dict[str, Any],
    *,
    project_id: str,
    run_id: str,
    requested_max_subhypotheses: int,
    redecomposed: bool,
) -> dict[str, Any]:
    """Describe the accepted V3 SH set separately from raw LLM candidates."""
    project = project if isinstance(project, dict) else {}
    decomposition = decomposition if isinstance(decomposition, dict) else {}
    sub_hypotheses = [
        item for item in project.get("sub_hypotheses", []) if isinstance(item, dict)
    ]
    kind_counts: dict[str, int] = {}
    task_count_by_sub_hypothesis: dict[str, int] = {}
    accepted_ids: list[str] = []
    all_subhypotheses_v3 = bool(sub_hypotheses)
    for item in sub_hypotheses:
        sub_hypothesis_id = str(item.get("id") or item.get("sub_hypothesis_id") or "").strip()
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        question = contract.get("research_question") if isinstance(contract.get("research_question"), dict) else {}
        kind = str(question.get("question_kind") or "UNRESOLVED")
        plan = (
            item.get("research_question_retrieval_plan")
            if isinstance(item.get("research_question_retrieval_plan"), dict)
            else {}
        )
        if sub_hypothesis_id:
            accepted_ids.append(sub_hypothesis_id)
            task_count_by_sub_hypothesis[sub_hypothesis_id] = len(
                [task for task in plan.get("tasks", []) if isinstance(task, dict)]
            )
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        all_subhypotheses_v3 = all_subhypotheses_v3 and (
            str(item.get("evidence_pipeline_schema") or "") == "research_question_evidence_v3"
            and bool(contract)
        )
    iteration_audit = (
        decomposition.get("llm_iteration_audit")
        if isinstance(decomposition.get("llm_iteration_audit"), dict)
        else {}
    )
    raw_count = int(
        iteration_audit.get("raw_llm_candidate_count")
        or iteration_audit.get("returned_sub_hypothesis_count")
        or len(accepted_ids)
    )
    rejected_count = int(
        iteration_audit.get("rejected_candidate_count")
        or max(0, raw_count - len(accepted_ids))
    )
    return {
        "project_id": project_id,
        "run_id": run_id,
        "requested_max_subhypotheses": requested_max_subhypotheses,
        "raw_llm_candidate_count": raw_count,
        "accepted_subhypothesis_count": len(accepted_ids),
        "rejected_candidate_count": rejected_count,
        "sub_hypothesis_ids": accepted_ids,
        "question_kind_counts": kind_counts,
        "task_count_by_sub_hypothesis": task_count_by_sub_hypothesis,
        "v3_redecomposition_applied": redecomposed,
        "all_subhypotheses_v3": all_subhypotheses_v3,
    }


def execute_research_question_retrieval_plans_v3(
    *,
    project: dict[str, Any],
    project_id: str,
    sub_hypothesis_ids: set[str],
    providers: list[str],
    use_llm: bool,
    search_papers_stratified: Any,
    import_literature_search_result: Any,
    execute_research_question_retrieval_plan: Any,
    search_foundational_context_v3: Any | None = None,
    groupchat_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Execute V3 plans fairly, with semantic deduplication and audit logs.

    One sub-hypothesis may not monopolize the run.  Task scheduling and V3
    evidence commits are deterministic; bounded candidate preparation overlaps
    network/PDF/LLM work before the single-writer commit phase.
    """

    def task_slot_key(task_id: str, slot_id: str) -> str:
        return f"{str(task_id or '').strip()}::{str(slot_id or '').strip()}"

    try:
        from ._literature_import import (
            commit_v3_prepared_literature_candidate_batch,
            prepare_v3_literature_candidate_batch,
        )
        from ._literature_search import (
            flatten_literature_results,
            literature_result_unique_key,
        )
        from ._project import (
            load_project,
            load_search,
            save_project,
            science_state_manager,
        )
        from ._research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            RETRIEVAL_TASK_SPEC_VERSION,
            bind_research_question_task_scope,
            build_question_retrieval_plan,
            validate_research_question_contract,
            validate_retrieval_work_item_v3,
        )
        from ._research_contract_coherence import (
            audit_research_question_contract,
            research_contract_coherence_gate,
        )
        from ._science_execution_policy import resolve_science_execution_policy
        from ._sh_retrieval import (
            DEFAULT_SH_LAYER_QUOTAS,
            build_sh_candidate_scope,
            build_sh_query_plan,
            build_targeted_gap_query,
            MAX_ADDITIONAL_WAVES,
            MAX_ADDITIONAL_PAPERS_PER_SLOT,
            load_sh_retrieval_run,
            select_sh_paper_quota,
            persist_sh_retrieval_run,
            synthesize_sh_evidence,
            unresolved_sh_obligations,
        )
    except ImportError:
        from _literature_import import (
            commit_v3_prepared_literature_candidate_batch,
            prepare_v3_literature_candidate_batch,
        )
        from _literature_search import (
            flatten_literature_results,
            literature_result_unique_key,
        )
        from _project import (
            load_project,
            load_search,
            save_project,
            science_state_manager,
        )
        from _research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            RETRIEVAL_TASK_SPEC_VERSION,
            bind_research_question_task_scope,
            build_question_retrieval_plan,
            validate_research_question_contract,
            validate_retrieval_work_item_v3,
        )
        from _research_contract_coherence import (
            audit_research_question_contract,
            research_contract_coherence_gate,
        )
        from _science_execution_policy import resolve_science_execution_policy
        from _sh_retrieval import (
            DEFAULT_SH_LAYER_QUOTAS,
            build_sh_candidate_scope,
            build_sh_query_plan,
            build_targeted_gap_query,
            MAX_ADDITIONAL_WAVES,
            MAX_ADDITIONAL_PAPERS_PER_SLOT,
            load_sh_retrieval_run,
            select_sh_paper_quota,
            persist_sh_retrieval_run,
            synthesize_sh_evidence,
            unresolved_sh_obligations,
        )

    if search_foundational_context_v3 is None:
        try:
            from ._literature_search import search_foundational_context_v3
        except ImportError:
            from _literature_search import search_foundational_context_v3

    project_taxonomy = _project_persisted_discipline_taxonomy(project)

    def decode_payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            loaded = json.loads(value)
            return dict(loaded) if isinstance(loaded, dict) else {}
        return {}

    def validate_provider_query_plans(plans: list[dict[str, Any]]) -> None:
        """Reject malformed SH batch plans before they reach a provider."""

        for plan in plans:
            if str(plan.get("schema_version") or "") != RETRIEVAL_TASK_SPEC_VERSION:
                raise ValueError(
                    "SH_PROVIDER_QUERY_PLAN_INVALID: expected retrieval_task_spec_v3"
                )
            validate_retrieval_work_item_v3(
                plan.get("retrieval_work_item_v3")
            )

    # Existing V3 contracts are the only legal plan input. Plans are
    # deterministically compiled in memory from that immutable declaration;
    # they are not operational state and are never written back into a SH.
    superseded_plan_audits: list[dict[str, Any]] = []
    active_subhypotheses: list[dict[str, Any]] = []
    coherence_blocked_ids: list[str] = []
    domain_blocked_ids: list[str] = []
    coherence_audits: dict[str, dict[str, Any]] = {}
    effective_policy = resolve_science_execution_policy(project, use_llm=use_llm)
    for item in project.get("sub_hypotheses", []):
        if not isinstance(item, dict):
            continue
        sub_id = str(item.get("id") or item.get("sub_hypothesis_id") or "").strip()
        if not sub_id or sub_id not in sub_hypothesis_ids:
            continue
        contract_raw = item.get("research_question_contract")
        try:
            contract = validate_research_question_contract(contract_raw)
        except (TypeError, ValueError):
            continue
        domain_contract = (
            contract.get("research_domain_contract")
            if isinstance(contract.get("research_domain_contract"), dict)
            else {}
        )
        domain_ready = bool(
            str(domain_contract.get("status") or "").upper() == "READY"
            and str(domain_contract.get("primary_domain_id") or "").strip()
            and any(str(value).strip() for value in domain_contract.get("active_domain_ids", []))
        )
        if not domain_ready:
            domain_blocked_ids.append(sub_id)
            coherence_audits[sub_id] = {
                "status": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
                "recovery_action": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
                "research_domain_contract": dict(domain_contract),
            }
            continue
        prior_audit = (
            (project.get("research_contract_coherence_audits_v3") or {}).get(sub_id)
            if isinstance(project.get("research_contract_coherence_audits_v3"), dict)
            else None
        )
        coherence_audit = audit_research_question_contract(
            contract,
            effective_policy,
            existing=prior_audit if isinstance(prior_audit, dict) else None,
        )
        coherence_audits[sub_id] = coherence_audit
        coherence_gate = research_contract_coherence_gate(coherence_audit)
        if coherence_gate.get("ready") is not True:
            coherence_blocked_ids.append(sub_id)
            continue
        plan = build_question_retrieval_plan(contract)
        if plan.get("schema_version") != RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION:
            continue
        active_subhypotheses.append(
            {
                "sub_hypothesis": item,
                "sub_hypothesis_id": sub_id,
                "contract": contract,
                "plan": plan,
            }
        )

    coherence_recovery_kind = (
        "REDECOMPOSE_RESEARCH_QUESTION_CONTRACTS"
        if any(
            str(coherence_audits[sub_id].get("status") or "")
            == "CONTRACT_SCOPE_INCOHERENT"
            for sub_id in coherence_blocked_ids
        )
        else "RESUME_CONTRACT_COHERENCE_AUDIT"
        if coherence_blocked_ids
        else ""
    )
    coherence_deferred_ids = [
        str(entry["sub_hypothesis_id"])
        for entry in active_subhypotheses
    ] if coherence_blocked_ids else []
    if coherence_blocked_ids:
        active_subhypotheses = []

    # No re-search for a plan which already completed at the same semantic
    # revision.  A former V2.0 completion is intentionally not considered
    # equivalent because it did not record semantic fingerprints.
    active_contexts: list[dict[str, Any]] = []
    branch_reports_by_id: dict[str, dict[str, Any]] = {
        sub_id: {
            "sub_hypothesis_id": sub_id,
            "status": str(coherence_audits[sub_id].get("status") or "COHERENCE_PENDING"),
            "task_count": 0,
            "search_count": 0,
            "imported_source_ids": [],
            "task_diagnostics": [],
            "contract_coherence_audit": coherence_audits[sub_id],
            "recovery_action": str(coherence_audits[sub_id].get("recovery_action") or ""),
        }
        for sub_id in coherence_blocked_ids
    }
    branch_reports_by_id.update({
        sub_id: {
            "sub_hypothesis_id": sub_id,
            "status": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
            "task_count": 0,
            "search_count": 0,
            "imported_source_ids": [],
            "task_diagnostics": [],
            "research_domain_contract": dict(
                coherence_audits[sub_id].get("research_domain_contract") or {}
            ),
            "recovery_action": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
        }
        for sub_id in domain_blocked_ids
    })
    for sub_id in coherence_deferred_ids:
        branch_reports_by_id[sub_id] = {
            "sub_hypothesis_id": sub_id,
            "status": "DEFERRED_FOR_CONTRACT_COHERENCE_RECOVERY",
            "task_count": 0,
            "search_count": 0,
            "imported_source_ids": [],
            "task_diagnostics": [],
            "contract_coherence_audit": coherence_audits[sub_id],
            "recovery_action": coherence_recovery_kind,
        }
    reused_completed_ids: list[str] = []
    reused_completed_task_rows: list[dict[str, Any]] = []
    shared_foundation_context_registry: dict[str, dict[str, Any]] = {}
    for entry in active_subhypotheses:
        sub_id = entry["sub_hypothesis_id"]
        plan = entry["plan"]
        base_tasks = [
            task for task in plan.get("tasks", [])
            if isinstance(task, dict)
        ]
        tasks = list(base_tasks)
        expected_ids = {str(task.get("task_id") or "") for task in base_tasks}
        prior = entry["sub_hypothesis"].get("research_question_retrieval_execution")
        prior = prior if isinstance(prior, dict) else {}
        prior_rows = [row for row in prior.get("results", []) if isinstance(row, dict)]
        prior_ids = {str(row.get("task_id") or "") for row in prior_rows}
        current_revision = str(plan.get("plan_revision") or "")
        prior_by_task = {
            str(row.get("task_id") or ""): row
            for row in prior_rows
            if str(row.get("plan_revision") or "") == current_revision
        }
        completed_same_revision = bool(
            str(prior.get("status") or "") == "COMPLETE"
            and expected_ids == prior_ids
            and current_revision
            and all(str(row.get("plan_revision") or "") == current_revision for row in prior_rows)
            and all(v3_retrieval_task_checkpoint_reusable(row) for row in prior_rows)
        )
        if completed_same_revision:
            reused_completed_ids.append(sub_id)
            reused_completed_task_rows.extend(
                {
                    "task_id": str(row.get("task_id") or ""),
                    "status": str(row.get("status") or "").upper(),
                    "checkpoint_reusable": True,
                    "reused_from_prior_execution": True,
                }
                for row in prior_rows
                if v3_retrieval_task_checkpoint_reusable(row)
            )
            branch_reports_by_id[sub_id] = {
                "sub_hypothesis_id": sub_id,
                "status": "REUSED_COMPLETED_V3_RETRIEVAL",
                "contract_coherence_audit": coherence_audits[sub_id],
                "task_count": len(tasks),
                "search_count": 0,
                "imported_source_ids": [],
                "task_diagnostics": [],
                "candidate_redundancy_totals": _v3_slot_profile_totals(tasks),
            }
            continue
        evidence_reader = None
        try:
            from ._project import science_state_manager
        except ImportError:
            from _project import science_state_manager
        try:
            evidence_reader = science_state_manager()
        except Exception:
            evidence_reader = None
        context = {
            **entry,
            "tasks": tasks,
            "sh_query_plan": build_sh_query_plan(
                tasks,
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                contract=entry["contract"],
                groupchat_id=str(groupchat_id or ""),
                run_id=str(run_id or ""),
                wave_id=f"{groupchat_id or 'groupchat'}:{run_id or 'run'}:{sub_id}:sh_discovery",
            ),
            "sh_discovery_state": {
                "status": "NOT_STARTED",
                "candidate_pool": [],
                "selected_corpus": {},
                "additional_searches": [],
            },
            "sh_run": {
                "schema_version": "sh_retrieval_run_v1",
                "run_id": f"shrun_{project_id}_{sub_id}_{plan.get('plan_revision') or 'current'}",
                "project_id": project_id,
                "sub_hypothesis_id": sub_id,
                "contract_revision": str(
                    entry["contract"].get("contract_revision")
                    or entry["contract"].get("declaration_hash")
                    or ""
                ),
                "prompt_revision": "sh_paper_review_v1",
                "model_id": "",
                "query_plan": build_sh_query_plan(
                    tasks,
                    project_id=project_id,
                    sub_hypothesis_id=sub_id,
                    contract=entry["contract"],
                    groupchat_id=str(groupchat_id or ""),
                    run_id=str(run_id or ""),
                    wave_id=f"{groupchat_id or 'groupchat'}:{run_id or 'run'}:{sub_id}:sh_discovery",
                ),
                "candidate_pool": [],
                "selected_corpus": {},
                "paper_reviews": [],
                "synthesis": {},
                "coverage": {},
                "unresolved_obligations": [],
                "additional_searches": [],
                "token_budget": {},
                "status": "PLANNED",
            },
            "sh_committed_records": {},
            "task_results": [],
            "task_diagnostics": [],
            "search_count": 0,
            "imported_source_ids": [],
            "seen_candidate_keys": set(),
            "imported_source_ids_set": set(),
            "query_results_by_fingerprint": {},
            "task_specs_by_fingerprint": {},
            "raw_candidate_pool_by_discovery_fingerprint": {},
            "prior_by_task": prior_by_task,
            "reusable_assertions_by_slot": {},
            "reusable_foundation_rationale_by_scope": {},
        }
        context["evidence_reader"] = evidence_reader
        sh_run_id = str(context["sh_run"].get("run_id") or "")
        resumed_sh_run = load_sh_retrieval_run(
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            run_id=sh_run_id,
            contract_revision=str(
                entry["contract"].get("contract_revision")
                or entry["contract"].get("declaration_hash")
                or ""
            ),
            query_plan=context["sh_query_plan"],
        )
        if isinstance(resumed_sh_run, dict):
            resumed_selection = (
                dict(resumed_sh_run.get("selected_corpus") or {})
                if isinstance(resumed_sh_run.get("selected_corpus"), dict)
                else {}
            )
            resumed_candidates = [
                dict(item)
                for item in resumed_selection.get("selected", [])
                if isinstance(item, dict)
            ]
            if not resumed_candidates:
                resumed_candidates = [
                    dict(item)
                    for item in resumed_sh_run.get("candidate_pool", [])
                    if isinstance(item, dict)
                ]
            if resumed_candidates:
                context["sh_discovery_state"].update({
                    "status": "PROVIDER_BATCH_READY",
                    "candidate_pool": resumed_candidates,
                    "selected_corpus": resumed_selection,
                    "resumed_from_run_id": sh_run_id,
                })
                for positive_task in [
                    candidate_task
                    for candidate_task in context["tasks"]
                    if isinstance(candidate_task, dict)
                    and str(candidate_task.get("query_mode") or "").upper()
                    == "POSITIVE_EVIDENCE"
                ]:
                    positive_spec = (
                        positive_task.get("retrieval_spec_v3")
                        if isinstance(positive_task.get("retrieval_spec_v3"), dict)
                        else {}
                    )
                    positive_fingerprint = str(
                        positive_spec.get("discovery_fingerprint")
                        or positive_spec.get("semantic_fingerprint")
                        or ""
                    ).strip()
                    if not positive_fingerprint:
                        continue
                    context["raw_candidate_pool_by_discovery_fingerprint"][positive_fingerprint] = {
                        "schema_version": "v3_raw_candidate_discovery_pool_v1",
                        "discovery_fingerprint": positive_fingerprint,
                        "query_mode": "POSITIVE_EVIDENCE",
                        "candidates": [dict(item) for item in resumed_candidates],
                        "source_task_ids": [],
                        "resumed_from_sh_run": True,
                    }
                context["sh_run"].update({
                    "resume_status": "COMPATIBLE_LOCAL_ARTIFACTS_LOADED",
                    "resumed_from_run_id": sh_run_id,
                    "candidate_pool": [dict(item) for item in resumed_sh_run.get("candidate_pool", []) if isinstance(item, dict)],
                    "selected_corpus": resumed_selection,
                    "paper_reviews": list(resumed_sh_run.get("paper_reviews") or []),
                })
        for record in project.get("papergraph", []):
            if not isinstance(record, dict):
                continue
            bindings = record.get("subhypothesis_bindings") if isinstance(record.get("subhypothesis_bindings"), list) else []
            bound_to_current = any(
                isinstance(binding, dict)
                and str(binding.get("research_question_contract_id") or "")
                == str(context["contract"].get("contract_id") or "")
                and str(binding.get("research_question_contract_revision") or "")
                == str(
                    context["contract"].get("contract_revision")
                    or context["contract"].get("declaration_hash")
                    or ""
                )
                and str(binding.get("research_question_contract_hash") or "")
                == str(
                    context["contract"].get("declaration_hash")
                    or context["contract"].get("contract_revision")
                    or ""
                )
                for binding in bindings
            )
            if not bound_to_current:
                continue
            source_id = str(record.get("paper_id") or "").strip()
            if source_id:
                context["sh_committed_records"][source_id] = dict(record)
            assertions = record.get("evidence_assertions_v4") if isinstance(record.get("evidence_assertions_v4"), list) else []
            if not assertions and source_id and evidence_reader is not None:
                storage = record.get("evidence_storage_v4") if isinstance(record.get("evidence_storage_v4"), dict) else {}
                assertion_ids = storage.get("assertion_ids") if isinstance(storage.get("assertion_ids"), list) else []
                for assertion_id in assertion_ids:
                    try:
                        assertion = evidence_reader.get_evidence_assertion(project_id, str(assertion_id))
                    except Exception:
                        continue
                    if isinstance(assertion, dict):
                        assertions.append(assertion)
            for assertion in assertions:
                if not isinstance(assertion, dict):
                    continue
                if (
                    str(assertion.get("research_question_contract_id") or "")
                    != str(contract.get("contract_id") or "")
                    or str(assertion.get("research_question_contract_revision") or "")
                    != str(
                        contract.get("contract_revision")
                        or contract.get("declaration_hash")
                        or ""
                    )
                    or str(assertion.get("research_question_contract_hash") or "")
                    != str(
                        contract.get("declaration_hash")
                        or contract.get("contract_revision")
                        or ""
                    )
                ):
                    continue
                assertion_id = str(assertion.get("assertion_id") or "").strip()
                assertion_task_id = str(
                    assertion.get("research_question_task_id") or ""
                ).strip()
                if not assertion_task_id:
                    continue
                contract_state = v3_contract_binding_state(
                    record, contract, assertion_task_id
                )
                contract_admission = contract_state["admission"]
                bundle_by_assertion_id = {
                    assertion_id: {
                        "coverage_bundle_id": str(bundle.get("coverage_bundle_id") or ""),
                        "coverage_bundle_kind": str(bundle.get("bundle_id") or ""),
                        "comparison_signature": str(bundle.get("comparison_signature") or ""),
                        "comparison_contract_id": str(bundle.get("comparison_contract_id") or ""),
                        "direct_pair_id": str(bundle.get("direct_pair_id") or ""),
                    }
                    for bundle in contract_admission.get("coverage_bundles", [])
                    if isinstance(bundle, dict)
                    for assertion_id in bundle.get("participating_assertion_ids", [])
                    if str(assertion_id)
                }
                is_foundation = contract_state["evidence_kind"] == "foundational_context"
                if is_foundation:
                    context["reusable_foundation_rationale_by_scope"].setdefault(
                        sub_id, []
                    ).append({"source_id": source_id, "assertion_id": assertion_id})
                for support in assertion.get("slot_support", []):
                    if not isinstance(support, dict):
                        continue
                    slot = str(support.get("slot_id") or "").strip()
                    if not slot or not source_id or not is_reusable_direct_slot_assertion(
                        assertion, record, contract, assertion_task_id, slot
                    ):
                        continue
                    bundle = bundle_by_assertion_id.get(assertion_id, {})
                    context["reusable_assertions_by_slot"].setdefault(
                        task_slot_key(assertion_task_id, slot), []
                    ).append({
                        "source_id": source_id,
                        "assertion_id": assertion_id,
                        "source_span_ids": list(support.get("source_span_ids") or []),
                        "paper_id": str(support.get("paper_id") or source_id),
                        "document_version_hash": str(
                            support.get("document_version_hash")
                            or assertion.get("document_version_hash")
                            or ""
                        ),
                        "coverage_bundle_id": str(bundle.get("coverage_bundle_id") or ""),
                        "coverage_bundle_kind": str(bundle.get("coverage_bundle_kind") or ""),
                        "comparison_signature": str(bundle.get("comparison_signature") or ""),
                        "comparison_contract_id": str(bundle.get("comparison_contract_id") or ""),
                        "direct_pair_id": str(bundle.get("direct_pair_id") or ""),
                    })
        # Project records are part of the no-repeat identity boundary.  The
        # source may be reused for a later V3 slot, but it is not rediscovered
        # or downloaded merely because another task asked a related question.
        for record in project.get("papergraph", []):
            if not isinstance(record, dict):
                continue
            bindings = record.get("subhypothesis_bindings") if isinstance(record.get("subhypothesis_bindings"), list) else []
            if not any(
                isinstance(binding, dict)
                and str(binding.get("sub_hypothesis_id") or "") == sub_id
                for binding in bindings
            ):
                continue
            candidate_key = str(literature_result_unique_key(record) or "").strip()
            if candidate_key:
                context["seen_candidate_keys"].add(candidate_key)
        active_contexts.append(context)
        branch_reports_by_id[sub_id] = {"sub_hypothesis_id": sub_id}

    for context in active_contexts:
        for task in context["tasks"]:
            if str(task.get("query_mode") or "").upper() != "FOUNDATIONAL_CONTEXT":
                continue
            foundation_contract = (
                task.get("foundation_context_contract")
                if isinstance(task.get("foundation_context_contract"), dict)
                else {}
            )
            shared_key = str(
                task.get("shared_context_key")
                or foundation_contract.get("shared_context_key")
                or ""
            ).strip()
            if not shared_key:
                continue
            registry = shared_foundation_context_registry.setdefault(
                shared_key,
                {
                    "owner_sub_hypothesis_id": context["sub_hypothesis_id"],
                    "source_ids": [],
                    "assertion_ids": [],
                    "task_id": "",
                },
            )
            task["shared_context_key"] = shared_key
            task["shared_context_owner_sub_hypothesis_id"] = registry[
                "owner_sub_hypothesis_id"
            ]

    def task_group(task: dict[str, Any]) -> int:
        mode = str(task.get("query_mode") or "").upper()
        if mode == "POSITIVE_EVIDENCE":
            return 0
        if mode == "FOUNDATIONAL_CONTEXT":
            return 1
        return 3

    def independent_confirmation_spec(
        task: dict[str, Any],
        contract: dict[str, Any],
        reuse_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """Compile a bounded V3 search for an underqualified reuse slot."""

        try:
            from ._research_question_contract import compile_independent_confirmation_retrieval_spec_v3
        except ImportError:
            from _research_question_contract import compile_independent_confirmation_retrieval_spec_v3
        slot = str(task.get("slot") or "").strip()
        return compile_independent_confirmation_retrieval_spec_v3(
            contract,
            slot=slot,
            required_source_role=str(task.get("required_source_role") or "DIRECT_PRIMARY_EVIDENCE"),
            missing_policy_requirements=list(reuse_verdict.get("missing_policy_requirements") or []),
        )

    def eligible_deferred_continuation(
        prior_result: dict[str, Any] | None,
    ) -> tuple[bool, str, list[str], dict[str, Any]]:
        """Allow one later V3 retry only after a deferred provider is eligible.

        This is deliberately checked at a fresh GroupChat run: no request waits
        or busy loops are introduced into the round-robin wave, and no legacy
        optimizer is allowed to reinterpret a deferred provider as a new causal
        retrieval route.
        """

        if not isinstance(prior_result, dict):
            return False, "no_prior_task_outcome", [], {}
        if str(prior_result.get("status") or "") != "PROVIDER_DEFERRED":
            return False, "prior_outcome_not_provider_deferred", [], {}
        continuation_attempts = max(
            0, int(prior_result.get("provider_continuation_attempts") or 0)
        )
        if continuation_attempts >= 1:
            return False, "continuation_attempt_limit_reached", [], {}
        execution = (
            prior_result.get("query_variant_execution_v3")
            if isinstance(prior_result.get("query_variant_execution_v3"), dict)
            else {}
        )
        deferred = execution.get("deferred_providers") if isinstance(execution.get("deferred_providers"), list) else []
        deferred_providers = list(dict.fromkeys(
            str(item.get("provider") or "").strip()
            for item in deferred
            if isinstance(item, dict) and str(item.get("provider") or "").strip()
        ))
        if not deferred_providers:
            return False, "deferred_provider_identity_missing", [], execution
        next_times = [
            float(item.get("next_eligible_at") or 0.0)
            for item in deferred
            if isinstance(item, dict)
        ]
        if next_times and max(next_times) > time.time():
            return False, "provider_cooldown_not_expired", deferred_providers, execution
        return True, "deferred_provider_cooldown_expired", deferred_providers, execution

    def positive_task_priority(task: dict[str, Any]) -> tuple[int, int, str]:
        """Order positive V3 slots by declared evidence value, not SH order."""

        slot = str(task.get("slot") or "")
        source_role = str(task.get("required_source_role") or "").upper()
        spec = task.get("retrieval_spec_v3") if isinstance(task.get("retrieval_spec_v3"), dict) else {}
        focus_axes = [axis for axis in spec.get("slot_focus_axes", []) if str(axis)]
        slot_value = {
            "phenomenon": 40,
            "direct_observation": 35,
            "target_condition": 30,
            "target_object": 25,
        }.get(slot, 20)
        direct_source_value = 100 if "DIRECT" in source_role or "PRIMARY" in source_role else 0
        return (-(direct_source_value + slot_value), -len(focus_axes), slot)

    def slot_reuse_verdict(
        task: dict[str, Any],
        reusable_assertions: list[dict[str, Any]],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate V3 reuse with per-slot sufficiency and coherence policy.

        Semantic query similarity is never evidence completion.  The verdict
        is computed only from already admission-qualified assertion records.
        """

        slot = str(task.get("slot") or "").strip()
        policy = task.get("reuse_policy") if isinstance(task.get("reuse_policy"), dict) else {}
        try:
            min_assertions = max(1, int(policy.get("min_admitted_assertion_count") or 1))
            min_spans = max(1, int(policy.get("min_distinct_span_count") or 1))
            min_papers = max(1, int(policy.get("min_distinct_paper_count") or 1))
        except (TypeError, ValueError):
            min_assertions, min_spans, min_papers = 1, 1, 1
        assertions = list(dict.fromkeys(
            str(item.get("assertion_id") or "")
            for item in reusable_assertions
            if isinstance(item, dict) and str(item.get("assertion_id") or "")
        ))
        spans = sorted({
            str(span_id)
            for item in reusable_assertions if isinstance(item, dict)
            for span_id in item.get("source_span_ids", [])
            if str(span_id)
        })
        papers = sorted({
            str(item.get("paper_id") or item.get("source_id") or "")
            for item in reusable_assertions
            if isinstance(item, dict) and str(item.get("paper_id") or item.get("source_id") or "")
        })
        bundle_id = str(policy.get("coverage_bundle_requirement") or "").strip()
        compatible_bundles: list[dict[str, str]] = []
        if bundle_id:
            seen_bundle_ids: set[str] = set()
            for item in reusable_assertions:
                if not isinstance(item, dict):
                    continue
                item_bundle_kind = str(item.get("coverage_bundle_kind") or "").strip()
                item_bundle_id = str(item.get("coverage_bundle_id") or "").strip()
                if (
                    item_bundle_id
                    and item_bundle_id not in seen_bundle_ids
                    and item_bundle_kind == bundle_id
                ):
                    seen_bundle_ids.add(item_bundle_id)
                    compatible_bundles.append({
                        "coverage_bundle_id": item_bundle_id,
                        "coverage_bundle_kind": item_bundle_kind,
                        "comparison_signature": str(item.get("comparison_signature") or ""),
                        "comparison_contract_id": str(
                            item.get("comparison_contract_id") or ""
                        ),
                        "direct_pair_id": str(item.get("direct_pair_id") or ""),
                    })
        comparison_contract = (
            contract.get("comparison_contract_v4")
            if isinstance(contract.get("comparison_contract_v4"), dict)
            else {}
        )
        expected_comparison_contract_id = str(
            comparison_contract.get("comparison_contract_id") or ""
        )
        comparison_required_pair_ids = sorted({
            "::".join(str(arm_id) for arm_id in pair)
            for pair in comparison_contract.get("target_comparison_pairs") or []
            if isinstance(pair, list)
            and len(pair) == 2
            and all(str(arm_id).strip() for arm_id in pair)
        })
        comparison_covered_pair_ids = sorted({
            str(bundle.get("direct_pair_id") or "")
            for bundle in compatible_bundles
            if (
                str(bundle.get("comparison_contract_id") or "")
                == expected_comparison_contract_id
                and str(bundle.get("direct_pair_id") or "")
            )
        })
        comparison_missing_pair_ids = [
            pair_id for pair_id in comparison_required_pair_ids
            if pair_id not in set(comparison_covered_pair_ids)
        ]
        direct_pair_coverage_complete = bool(
            comparison_contract
            and comparison_required_pair_ids
            and not comparison_missing_pair_ids
        )
        sufficient_base = (
            len(assertions) >= min_assertions
            and len(spans) >= min_spans
            and len(papers) >= min_papers
        )
        requires_independent = bool(policy.get("require_independent_confirmation"))
        independent_short = requires_independent and len(papers) < max(2, min_papers)
        # Project-level comparability is intentionally not a per-paper reuse
        # gate. A source that covers one declared arm remains reusable.
        bundle_short = bool(bundle_id) and not compatible_bundles and not comparison_contract
        if sufficient_base and not independent_short and not bundle_short:
            verdict = "SATISFIED_BY_REUSE"
            dispatch = "SKIPPED_SLOT_POLICY_SATISFIED"
        elif assertions:
            verdict = "SATISFIED_BY_REUSE_BUT_DIVERSITY_SHORT" if (independent_short or bundle_short) else "PARTIALLY_SATISFIED_REQUIRES_TARGETED_SEARCH"
            dispatch = "REQUIRED_SLOT_DIVERSITY_OR_COHERENCE_SHORTAGE"
        else:
            verdict = "UNSATISFIED"
            dispatch = "REQUIRED_SLOT_UNSATISFIED"
        return {
            "slot_id": slot,
            "policy": dict(policy),
            "verdict": verdict,
            "provider_dispatch_status": dispatch,
            "admitted_assertion_ids": assertions,
            "distinct_span_ids": spans,
            "distinct_paper_ids": papers,
            "coverage_bundle_id": (
                compatible_bundles[0]["coverage_bundle_id"]
                if compatible_bundles and not bundle_short else ""
            ),
            "coverage_bundle_kind": (
                compatible_bundles[0]["coverage_bundle_kind"]
                if compatible_bundles and not bundle_short else ""
            ),
            "comparison_signature": (
                compatible_bundles[0]["comparison_signature"]
                if compatible_bundles and not bundle_short else ""
            ),
            "comparison_coverage_bundle_ids": sorted(
                bundle["coverage_bundle_id"] for bundle in compatible_bundles
            ),
            "comparison_target_pair_ids": comparison_required_pair_ids,
            "comparison_direct_pair_ids": comparison_covered_pair_ids,
            "comparison_missing_direct_pair_ids": comparison_missing_pair_ids,
            "direct_pair_coverage_complete": direct_pair_coverage_complete,
            "independent_confirmation_required": requires_independent,
            "missing_policy_requirements": [
                *([] if len(assertions) >= min_assertions else ["min_admitted_assertion_count"]),
                *([] if len(spans) >= min_spans else ["min_distinct_span_count"]),
                *([] if len(papers) >= min_papers else ["min_distinct_paper_count"]),
                *([] if not independent_short else ["independent_confirmation"]),
                *(
                    []
                    if not bundle_short
                    else [f"direct_pair:{pair_id}" for pair_id in comparison_missing_pair_ids]
                    if comparison_contract
                    else [f"coverage_bundle:{bundle_id}"]
                ),
            ],
        }

    def prior_outcome_satisfies_current_slot_policy(
        task: dict[str, Any],
        prior_result: dict[str, Any] | None,
        reuse_verdict: dict[str, Any],
    ) -> bool:
        """Keep V3 idempotence without treating stale shortfalls as complete.

        A completed positive task can be replayed only after its retained,
        currently hydrated assertion records satisfy the active slot policy.
        This makes a prior provider attempt an audit record, not evidence of
        present coverage.  Resolution and shared-context tasks keep their
        normal task-level idempotence because positive-slot reuse cannot
        complete them.
        """

        if not isinstance(prior_result, dict):
            return False
        if not v3_retrieval_task_checkpoint_reusable(prior_result):
            return False
        if str(task.get("query_mode") or "").upper() != "POSITIVE_EVIDENCE":
            return True
        return str(reuse_verdict.get("verdict") or "") == "SATISFIED_BY_REUSE"

    def slot_candidate_scope(
        contract: dict[str, Any],
        spec: dict[str, Any],
        *,
        sub_hypothesis_id: str,
        evidence_slot: str,
        query_branch: str,
    ) -> dict[str, Any]:
        """Compile the only metadata admission input for one V3 slot task."""
        blueprint = (
            spec.get("query_blueprint_v3")
            if isinstance(spec.get("query_blueprint_v3"), dict)
            else {}
        )
        query_ast = (
            blueprint.get("query_ast_v3")
            if isinstance(blueprint.get("query_ast_v3"), dict)
            else {}
        )
        slot_anchors = [
            str(term).strip()
            for clause in query_ast.get("all_of", [])
            if isinstance(clause, dict)
            and str(clause.get("role") or "") == "slot_requirement"
            for term in (clause.get("terms") or [])
            if str(term).strip()
        ]
        return {
            "schema_version": "slot_candidate_scope_v3",
            "research_question_contract_id": str(
                contract.get("contract_id") or ""
            ),
            "research_question_contract_hash": str(
                contract.get("declaration_hash")
                or contract.get("contract_revision")
                or ""
            ),
            "sub_hypothesis_id": str(sub_hypothesis_id or ""),
            "evidence_slot": str(evidence_slot or ""),
            "query_branch": query_branch,
            "scope_anchor_groups": dict(spec.get("scope_anchor_groups") or {}),
            "query_blueprint_v3": dict(blueprint),
            "slot_focus_axes": list(spec.get("slot_focus_axes") or []),
            "slot_anchors": list(dict.fromkeys(slot_anchors)),
        }

    # Compile one SH-wide discovery scope after task-local scopes are available.
    # Provider discovery uses the union only for recall; each imported paper is
    # still aligned against its task-local scope during evidence preparation.
    for context in active_contexts:
        task_scopes = []
        for task in context["tasks"]:
            if str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT":
                continue
            spec = (
                task.get("retrieval_spec_v3")
                if isinstance(task.get("retrieval_spec_v3"), dict)
                else {}
            )
            query_branch = str(
                spec.get("query_branch")
                or task.get("query_branch")
                or f"{context['sub_hypothesis_id']}:{task.get('slot') or task.get('requirement') or task.get('task_id')}"
            ).strip()
            task_scopes.append(slot_candidate_scope(
                context["contract"],
                spec,
                sub_hypothesis_id=str(context["sub_hypothesis_id"] or ""),
                evidence_slot=str(
                    spec.get("slot_identity")
                    or task.get("slot")
                    or task.get("requirement")
                    or ""
                ),
                query_branch=query_branch,
            ))
        context["sh_candidate_scope"] = build_sh_candidate_scope(
            context["contract"],
            task_scopes,
        )
        context["sh_discovery_state"]["query_branch_count"] = int(
            context["sh_query_plan"].get("branch_count") or 0
        )

    # Wave 0 gives every SH a principal positive retrieval. Wave 1 handles
    # V3-only context candidates. Remaining positives and resolution tasks
    # then rotate by index, preventing SH1's slot count from starving SH2.
    # Semantic variants remain inside one provider dispatch for the same task;
    # they are never extra scheduler tasks.
    schedule: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    positive_by_context: dict[str, list[dict[str, Any]]] = {}
    foundation_by_context: dict[str, list[dict[str, Any]]] = {}
    resolution_by_context: dict[str, list[dict[str, Any]]] = {}
    for context in active_contexts:
        sub_id = context["sub_hypothesis_id"]
        positive_by_context[sub_id] = sorted(
            [task for task in context["tasks"] if task_group(task) == 0],
            key=positive_task_priority,
        )
        foundation_by_context[sub_id] = [task for task in context["tasks"] if task_group(task) == 1]
        resolution_by_context[sub_id] = [task for task in context["tasks"] if task_group(task) == 3]

    def sh_paper_reviews(context: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Build compact paper review rows from committed SH records only."""

        reader = context.get("evidence_reader")
        reviews: list[dict[str, Any]] = []
        committed = context.get("sh_committed_records")
        if not isinstance(committed, Mapping):
            return reviews
        for source_id, record in committed.items():
            if not isinstance(record, Mapping):
                continue
            assertions = (
                [dict(item) for item in record.get("evidence_assertions_v4", []) if isinstance(item, Mapping)]
                if isinstance(record.get("evidence_assertions_v4"), list)
                else []
            )
            if not assertions and reader is not None:
                assertion_ids = (
                    record.get("evidence_assertion_ids")
                    if isinstance(record.get("evidence_assertion_ids"), list)
                    else []
                )
                for assertion_id in assertion_ids:
                    try:
                        assertion = reader.get_evidence_assertion(project_id, str(assertion_id))
                    except Exception:
                        continue
                    if isinstance(assertion, dict):
                        assertions.append(assertion)
            reviews.append({
                "paper_id": str(source_id),
                "review_status": "COMPLETED" if assertions else "COMPLETED_WITHOUT_ASSERTIONS",
                "assertions": assertions,
                "slot_supports": list(record.get("slot_supports_v4") or [])
                if isinstance(record.get("slot_supports_v4"), list)
                else [],
                "document_proposition_artifact": dict(record.get("document_proposition_artifact") or {})
                if isinstance(record.get("document_proposition_artifact"), dict)
                else {},
            })
        return reviews

    def sh_unresolved_obligations(context: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        reviews = sh_paper_reviews(context)
        synthesis = synthesize_sh_evidence(context["contract"], reviews)
        coverage = synthesis.get("coverage") if isinstance(synthesis.get("coverage"), dict) else {}
        required_slots = [
            str(task.get("slot") or task.get("requirement") or "")
            for task in context.get("tasks", [])
            if isinstance(task, Mapping)
            and str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
            and str(task.get("slot") or task.get("requirement") or "")
        ]
        obligations = unresolved_sh_obligations(coverage, required_slots=required_slots)
        return obligations, synthesis

    # All non-foundational branches for one SH belong to one discovery wave.
    # The first branch performs the provider batch; the remaining branches
    # consume that SH pool locally.  Foundation and resolution lanes remain
    # separate because they have different evidence semantics.
    for context in active_contexts:
        sub_id = context["sub_hypothesis_id"]
        for task in positive_by_context.get(sub_id, []):
            schedule.append((0, context, task))
    for context in active_contexts:
        entries = foundation_by_context.get(context["sub_hypothesis_id"], [])
        for task in entries:
            schedule.append((1, context, task))
    max_resolution = max((len(rows) for rows in resolution_by_context.values()), default=0)
    for offset in range(max_resolution):
        for context in active_contexts:
            rows = resolution_by_context.get(context["sub_hypothesis_id"], [])
            if offset < len(rows):
                schedule.append((2 + offset, context, rows[offset]))
    execution_order: list[dict[str, Any]] = []
    retrieval_run_context = {
        "schema_version": "v3_retrieval_run_context_v1",
        "project_id": project_id,
        "groupchat_id": str(groupchat_id or ""),
        "run_id": str(run_id or ""),
        "plan_revisions_by_sub_hypothesis": {
            context["sub_hypothesis_id"]: str(context["plan"].get("plan_revision") or "")
            for context in active_contexts
        },
        "execution_summary_by_sh": {},
        "raw_candidate_pool_by_discovery_fingerprint": {},
    }
    shared_foundation_consumer_count = sum(
        len(
            [
                context
                for context in active_contexts
                if str(context["sub_hypothesis_id"])
                != str(registry.get("owner_sub_hypothesis_id") or "")
                and any(
                    str(task.get("shared_context_key") or "").strip()
                    == shared_key
                    for task in context["tasks"]
                )
            ]
        )
        for shared_key, registry in shared_foundation_context_registry.items()
        if isinstance(registry, dict)
    )
    log_event(
        "SCIENCE",
        "v3_retrieval_schedule_initialized",
        project_id=project_id,
        scheduled_task_count=len(schedule),
        declared_sub_hypothesis_count=len(
            [
                item
                for item in project.get("sub_hypotheses", [])
                if isinstance(item, dict)
                and str(item.get("id") or item.get("sub_hypothesis_id") or "")
                in sub_hypothesis_ids
            ]
        ),
        execution_eligible_sub_hypothesis_count=len(active_contexts),
        domain_blocked_sub_hypothesis_count=len(domain_blocked_ids),
        coherence_blocked_sub_hypothesis_count=len(coherence_blocked_ids),
        shared_foundation_context_count=len(shared_foundation_context_registry),
        shared_foundation_consumer_count=shared_foundation_consumer_count,
        scheduler_policy="round_robin_by_subhypothesis_v3",
    )
    initial_schedule_length = len(schedule)
    targeted_gap_wave_added = False
    active_wave: int | None = None
    for sequence_index, (wave, context, task) in enumerate(schedule, start=1):
        if not targeted_gap_wave_added and sequence_index == initial_schedule_length + 1:
            targeted_gap_wave_added = True
            targeted_task_count = 0
            for gap_context in active_contexts:
                obligations, preliminary_synthesis = sh_unresolved_obligations(gap_context)
                if not obligations:
                    continue
                gap_sub_id = str(gap_context.get("sub_hypothesis_id") or "")
                base_positive_tasks = [
                    candidate_task
                    for candidate_task in gap_context.get("tasks", [])
                    if isinstance(candidate_task, dict)
                    and str(candidate_task.get("query_mode") or "").upper()
                    == "POSITIVE_EVIDENCE"
                ]
                for obligation in obligations:
                    slot_id = str(obligation.get("slot_id") or "").strip()
                    base_task = next(
                        (
                            candidate_task
                            for candidate_task in base_positive_tasks
                            if str(
                                candidate_task.get("slot")
                                or candidate_task.get("requirement")
                                or ""
                            ).strip()
                            == slot_id
                        ),
                        None,
                    )
                    if not isinstance(base_task, dict) or not slot_id:
                        continue
                    base_spec = (
                        dict(base_task.get("retrieval_spec_v3") or {})
                        if isinstance(base_task.get("retrieval_spec_v3"), dict)
                        else {}
                    )
                    gap_query = build_targeted_gap_query(
                        obligation,
                        gap_context["contract"],
                        sub_hypothesis_id=gap_sub_id,
                    )
                    query_text = str(gap_query.get("query_text") or "").strip()
                    if not query_text:
                        continue
                    gap_branch = str(gap_query.get("branch_id") or "").strip()
                    gap_fingerprint = "sha256:" + sha256(
                        (gap_branch + "|" + query_text).encode("utf-8", errors="ignore")
                    ).hexdigest()
                    targeted_task = dict(base_task)
                    targeted_task.update({
                        "task_id": f"{str(base_task.get('task_id') or slot_id)}:targeted_gap_1",
                        "query_mode": "POSITIVE_EVIDENCE",
                        "slot": slot_id,
                        "requirement": slot_id,
                        "targeted_gap_retrieval": True,
                        "targeted_gap_wave": 1,
                        "targeted_gap_obligation": dict(obligation),
                        "retrieval_spec_v3": {
                            **base_spec,
                            "provider_query": query_text,
                            "query_branch": gap_branch,
                            "semantic_fingerprint": gap_fingerprint,
                            "discovery_fingerprint": gap_fingerprint,
                            "candidate_budget": MAX_ADDITIONAL_PAPERS_PER_SLOT,
                            "layer_quotas": {
                                "L2_top_latest": 3,
                                "L4_regular": 2,
                                "L0_review": 0,
                                "L1_milestone": 0,
                                "L3_preprint": 0,
                            },
                            "targeted_gap_retrieval": True,
                        },
                    })
                    gap_context["tasks"].append(targeted_task)
                    schedule.append((max(2, (active_wave or 0) + 1), gap_context, targeted_task))
                    targeted_task_count += 1
                gap_context["sh_run"].update({
                    "gap_wave_status": "SCHEDULED",
                    "gap_wave_obligations": list(obligations),
                    "preliminary_synthesis": preliminary_synthesis,
                })
            log_event(
                "SCIENCE",
                "v3_targeted_gap_wave_scheduled",
                project_id=project_id,
                targeted_task_count=targeted_task_count,
                wave_limit=MAX_ADDITIONAL_WAVES,
                papers_per_slot=MAX_ADDITIONAL_PAPERS_PER_SLOT,
            )
        if wave != active_wave:
            if active_wave is not None:
                log_event(
                    "SCIENCE",
                    "v3_retrieval_wave_completed",
                    project_id=project_id,
                    wave_index=active_wave,
                )
            active_wave = wave
            log_event(
                "SCIENCE",
                "v3_retrieval_wave_started",
                project_id=project_id,
                wave_index=wave,
            )
        sub_id = context["sub_hypothesis_id"]
        task_id = str(task.get("task_id") or "").strip()
        spec = task.get("retrieval_spec_v3") if isinstance(task.get("retrieval_spec_v3"), dict) else {}
        targeted_gap_retrieval = bool(task.get("targeted_gap_retrieval"))
        query = str(spec.get("provider_query") or "").strip()
        query_branch = str(spec.get("query_branch") or f"{sub_id}:{task.get('slot') or task.get('requirement') or task_id}").strip()
        fingerprint = str(spec.get("semantic_fingerprint") or "").strip()
        discovery_fingerprint = str(
            spec.get("discovery_fingerprint") or fingerprint
        ).strip()
        slot_identity = str(
            spec.get("slot_identity") or task.get("slot") or task.get("requirement") or ""
        ).strip()
        semantic_execution_key = "|".join((fingerprint, slot_identity))
        plan_revision = str(context["plan"].get("plan_revision") or "")
        profile = v3_research_question_slot_candidate_profile(task)
        if targeted_gap_retrieval:
            profile = {
                **profile,
                "profile": "v3_targeted_gap_retrieval",
                "candidate_budget": MAX_ADDITIONAL_PAPERS_PER_SLOT,
                "layer_quotas": {
                    "L2_top_latest": 3,
                    "L4_regular": 2,
                    "L0_review": 0,
                    "L1_milestone": 0,
                    "L3_preprint": 0,
                },
            }
        result: dict[str, Any] = {
            "schema_version": "retrieval_task_execution_v3",
            "plan_schema_version": RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            "task_id": task_id,
            "executed_query": query,
            "query_branch": query_branch,
            "query_fingerprint": fingerprint,
            "discovery_fingerprint": discovery_fingerprint,
            "retrieval_purpose": str(
                spec.get("retrieval_purpose") or "PRIMARY_SLOT_RETRIEVAL"
            ),
            "targeted_gap_retrieval": targeted_gap_retrieval,
            "targeted_gap_wave": int(task.get("targeted_gap_wave") or 0),
            "targeted_gap_obligation": dict(task.get("targeted_gap_obligation") or {})
            if isinstance(task.get("targeted_gap_obligation"), dict)
            else {},
            "plan_revision": plan_revision,
            "retrieval_work_item_v3": dict(task.get("retrieval_work_item_v3") or {}),
            "retrieval_obligation_v3": dict(task.get("retrieval_obligation_v3") or {}),
            "source_ids": [],
            "new_source_ids": [],
            "reused_source_ids": [],
            "assertion_ids": [],
            "candidate_redundancy_profile": profile,
            "excluded_candidate_key_count": len(context["seen_candidate_keys"]),
            "candidate_count": 0,
            "metadata_kept_count": 0,
            "fulltext_available_count": 0,
            "alignment_completed_count": 0,
            "alignment_not_executed_count": 0,
            "alignment_integrity_error_count": 0,
            "target_slot_terminal_positive_count": 0,
            "target_slot_pending_pair_count": 0,
            "direct_slot_admitted_count": 0,
            "direct_slot_admitted_ids": [],
            "direct_slot_admitted_source_ids": [],
            "direct_slot_admitted_assertion_ids_by_slot": {},
            "direct_slot_admitted_source_ids_by_slot": {},
            "direct_slot_admitted_span_ids_by_slot": {},
            "foundation_context_count": 0,
            "background_only_count": 0,
            "contract_rejected_count": 0,
            "raw_provider_result_count": 0,
            "configured_providers": [],
            "dispatched_providers": [],
            "skipped_providers": [],
            "deferred_provider_count": 0,
            "provider_error_count": 0,
            "provider_submission_count": 0,
            "provider_terminal_response_count": 0,
            "local_query_compilation_rejection_count": 0,
            "provider_continuation_attempts": 0,
            "slot_policy_verdict": "UNASSESSED",
            "provider_dispatch_status": "NOT_DISPATCHED",
            "provider_dispatch_reason": "",
            "independent_confirmation_required": False,
            "reused_direct_slot_admitted_assertion_count": 0,
            "reused_direct_slot_admitted_source_count": 0,
            "new_direct_slot_admitted_source_count": 0,
            "direct_slot_admitted_span_count": 0,
            "coverage_bundle_id": "",
            "coverage_bundle_kind": "",
            "comparison_signature": "",
            "comparison_coverage_bundle_ids": [],
            "comparison_target_pair_ids": [],
            "comparison_direct_pair_ids": [],
            "comparison_missing_direct_pair_ids": [],
            "direct_pair_coverage_complete": False,
            "comparison_retrieval_phase_v4": {},
            "assertion_admission_status": "",
            "scientific_obligation_status": "",
            "comparison_obligation_diagnostics": {},
            "comparison_candidate_diagnostics": [],
            "raw_candidate_pool_provenance": {},
            "failure_stage": "",
            "exception_type": "",
            "exception_message": "",
        }
        diagnostic: dict[str, Any] = {
            "task_id": task_id,
            "sub_hypothesis_id": sub_id,
            "slot": str(task.get("slot") or task.get("requirement") or ""),
            "query_mode": str(task.get("query_mode") or ""),
            "query_branch": query_branch,
            "query_fingerprint": fingerprint,
            "discovery_fingerprint": discovery_fingerprint,
            "wave": wave,
            "sequence_index": sequence_index,
            "candidate_redundancy_profile": profile,
            "groupchat_id": str(groupchat_id or ""),
            "run_id": str(run_id or ""),
            "retrieval_wave_id": f"{groupchat_id or 'groupchat'}:{run_id or 'run'}:wave_{wave}",
        }
        execution_order.append({
            "sequence_index": sequence_index,
            "wave": wave,
            "sub_hypothesis_id": sub_id,
            "task_id": task_id,
            "slot": diagnostic["slot"],
            "query_mode": diagnostic["query_mode"],
            "query_branch": query_branch,
            "query_fingerprint": fingerprint,
            "discovery_fingerprint": discovery_fingerprint,
            "new_candidate_budget": int(profile.get("candidate_budget") or 0),
            "excluded_candidate_key_count": len(context["seen_candidate_keys"]),
            "retrieval_purpose": str(spec.get("retrieval_purpose") or "PRIMARY_SLOT_RETRIEVAL"),
        })
        log_event("SCIENCE", "v3_retrieval_task_scheduled", project_id=project_id, **execution_order[-1])
        log_event(
            "SCIENCE",
            "v3_retrieval_task_started",
            project_id=project_id,
            wave_index=wave,
            sub_hypothesis_id=sub_id,
            task_id=task_id,
            slot=diagnostic["slot"],
            query_mode=diagnostic["query_mode"],
            query_fingerprint=fingerprint,
            new_candidate_budget=int(profile.get("candidate_budget") or 0),
            excluded_candidate_key_count=len(context["seen_candidate_keys"]),
        )

        failure_stage = "task_preflight"
        preflight_error: Exception | None = None
        prior_result = context["prior_by_task"].get(task_id)
        comparison_contract = (
            context["contract"].get("comparison_contract_v4")
            if isinstance(context["contract"].get("comparison_contract_v4"), dict)
            else {}
        )
        comparison_execution_phase: dict[str, Any] = {}
        if comparison_contract:
            prior_phase = (
                prior_result.get("comparison_retrieval_phase_v4")
                if isinstance(prior_result, dict)
                and isinstance(prior_result.get("comparison_retrieval_phase_v4"), dict)
                else {}
            )
            phase = "ARM_FIRST_PHASE"
            transition_reason = "initial_parallel_arm_and_direct_pair_acquisition"
            if (
                str(prior_phase.get("phase") or "") == "ARM_FIRST_PHASE"
                and prior_phase.get("arm_first_provider_execution_complete") is True
                and prior_phase.get("comparison_arm_coverage_ready") is True
                and prior_phase.get("comparison_synthesis_ready") is False
            ):
                phase = "COMPARABILITY_FOLLOWUP_PHASE"
                transition_reason = "both_arms_collected_but_comparability_audit_remains_incomplete"
            comparison_execution_phase = {
                "schema_version": "comparison_retrieval_phase_v4",
                "phase": phase,
                "transition_reason": transition_reason,
            }
            result["comparison_retrieval_phase_v4"] = dict(
                comparison_execution_phase
            )
            diagnostic["comparison_retrieval_phase_v4"] = dict(
                comparison_execution_phase
            )
        slot = str(task.get("slot") or "")
        shared_context_key = str(task.get("shared_context_key") or "").strip()
        shared_context = (
            shared_foundation_context_registry.get(shared_context_key)
            if shared_context_key
            else None
        )
        deferred_continuation_allowed = False
        deferred_continuation_reason = ""
        deferred_continuation_providers: list[str] = []
        deferred_continuation_execution: dict[str, Any] = {}
        try:
            (
                deferred_continuation_allowed,
                deferred_continuation_reason,
                deferred_continuation_providers,
                deferred_continuation_execution,
            ) = eligible_deferred_continuation(prior_result)
        except Exception as exc:
            preflight_error = exc
        if preflight_error is None and deferred_continuation_allowed:
            result["provider_continuation_attempts"] = (
                int(prior_result.get("provider_continuation_attempts") or 0) + 1
            )
            diagnostic.update({
                "deferred_provider_continuation": True,
                "deferred_provider_continuation_reason": deferred_continuation_reason,
                "deferred_provider_continuation_providers": deferred_continuation_providers,
            })
            log_event(
                "SCIENCE",
                "v3_deferred_provider_continuation_started",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                research_question_task_id=task_id,
                evidence_slot=diagnostic["slot"],
                query_branch=query_branch,
                plan_revision=plan_revision,
                semantic_fingerprint=fingerprint,
                continuation_attempt=result["provider_continuation_attempts"],
                deferred_providers=deferred_continuation_providers,
            )
        reusable_assertions = context["reusable_assertions_by_slot"].get(
            task_slot_key(task_id, slot), []
        )
        reuse_verdict: dict[str, Any] = {}
        if preflight_error is None:
            try:
                failure_stage = "reuse_policy_evaluation"
                reuse_verdict = slot_reuse_verdict(
                    task, reusable_assertions, context["contract"]
                )
            except Exception as exc:
                preflight_error = exc
        independent_confirmation_required = False
        if preflight_error is None:
            result["slot_policy_verdict"] = reuse_verdict["verdict"]
            result["provider_dispatch_status"] = reuse_verdict["provider_dispatch_status"]
            result["provider_dispatch_reason"] = ",".join(
                reuse_verdict["missing_policy_requirements"]
            )
            result["direct_slot_admitted_span_count"] = len(
                reuse_verdict["distinct_span_ids"]
            )
            independent_confirmation_required = (
                str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
                and reuse_verdict["verdict"] in {
                    "SATISFIED_BY_REUSE_BUT_DIVERSITY_SHORT",
                    "PARTIALLY_SATISFIED_REQUIRES_TARGETED_SEARCH",
                }
            )
            result["independent_confirmation_required"] = (
                independent_confirmation_required
            )
        if preflight_error is None and independent_confirmation_required:
            try:
                failure_stage = "independent_confirmation_compilation"
                spec = independent_confirmation_spec(
                    task, context["contract"], reuse_verdict
                )
            except Exception as exc:
                preflight_error = exc
                spec = {}
        if preflight_error is None and independent_confirmation_required:
            query = str(spec.get("provider_query") or query).strip()
            query_branch = str(spec.get("query_branch") or query_branch).strip()
            fingerprint = str(spec.get("semantic_fingerprint") or fingerprint).strip()
            discovery_fingerprint = str(
                spec.get("discovery_fingerprint") or fingerprint
            ).strip()
            semantic_execution_key = "|".join((fingerprint, slot_identity))
            result["executed_query"] = query
            result["query_branch"] = query_branch
            result["query_fingerprint"] = fingerprint
            result["discovery_fingerprint"] = discovery_fingerprint
            result["retrieval_purpose"] = "INDEPENDENT_CONFIRMATION"
            result["provider_dispatch_status"] = "REQUIRED_INDEPENDENT_CONFIRMATION"
            result["provider_dispatch_reason"] = ",".join(
                reuse_verdict["missing_policy_requirements"]
            )
            diagnostic.update({
                "retrieval_purpose": "INDEPENDENT_CONFIRMATION",
                "status": "independent_confirmation_required",
                "query_branch": query_branch,
                "query_fingerprint": fingerprint,
                "discovery_fingerprint": discovery_fingerprint,
                "missing_policy_requirements": list(
                    reuse_verdict["missing_policy_requirements"]
                ),
            })
            execution_order[-1].update({
                "query_branch": query_branch,
                "query_fingerprint": fingerprint,
                "discovery_fingerprint": discovery_fingerprint,
                "retrieval_purpose": "INDEPENDENT_CONFIRMATION",
                "provider_dispatch_status": "REQUIRED_INDEPENDENT_CONFIRMATION",
                "provider_dispatch_reason": list(
                    reuse_verdict["missing_policy_requirements"]
                ),
            })
            log_event(
                "SCIENCE",
                "v3_retrieval_task_rescheduled_for_independent_confirmation",
                project_id=project_id,
                wave_index=wave,
                sub_hypothesis_id=sub_id,
                task_id=task_id,
                slot=slot,
                query_branch=query_branch,
                query_fingerprint=fingerprint,
                existing_distinct_paper_count=len(reuse_verdict["distinct_paper_ids"]),
                existing_distinct_span_count=len(reuse_verdict["distinct_span_ids"]),
                missing_policy_requirements=list(
                    reuse_verdict["missing_policy_requirements"]
                ),
            )
        prior_outcome_reusable = False
        if (
            preflight_error is None
            and isinstance(prior_result, dict)
            and not deferred_continuation_allowed
        ):
            try:
                failure_stage = "prior_outcome_reuse_evaluation"
                prior_outcome_reusable = prior_outcome_satisfies_current_slot_policy(
                    task, prior_result, reuse_verdict
                )
            except Exception as exc:
                preflight_error = exc
        if preflight_error is not None:
            exception_type = type(preflight_error).__name__
            exception_message = str(preflight_error)[:180]
            result.update({
                "status": "RETRIEVAL_EXECUTION_ERROR",
                "provider_dispatch_status": "INTERNAL_RETRIEVAL_EXECUTION_ERROR",
                "provider_dispatch_reason": f"internal_failure_stage:{failure_stage}",
                "failure_stage": failure_stage,
                "exception_type": exception_type,
                "exception_message": exception_message,
            })
            diagnostic.update({
                "status": "retrieval_execution_error",
                "failure_stage": failure_stage,
                "exception_type": exception_type,
                "exception_message": exception_message,
                "error": f"{exception_type}: {exception_message}",
                "coverage_status": "RETRIEVAL_EXECUTION_ERROR",
            })
            log_event(
                "SCIENCE",
                "v3_retrieval_task_preflight_error",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                task_id=task_id,
                failure_stage=failure_stage,
                exception_type=exception_type,
                exception_message=exception_message,
            )
        elif (
            str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT"
            and isinstance(shared_context, dict)
            and shared_context.get("owner_sub_hypothesis_id") != sub_id
            and shared_context.get("source_ids")
        ):
            reused_source_ids = list(shared_context.get("source_ids") or [])
            reused_assertion_ids = list(shared_context.get("assertion_ids") or [])
            result.update({
                "status": "REUSED_SHARED_FOUNDATIONAL_CONTEXT",
                "source_ids": reused_source_ids,
                "reused_source_ids": reused_source_ids,
                "assertion_ids": reused_assertion_ids,
                "foundation_context_count": len(reused_source_ids),
                "foundation_context_execution": {
                    "status": "REUSED_SHARED_FOUNDATIONAL_CONTEXT",
                    "shared_context_key": shared_context_key,
                    "owner_sub_hypothesis_id": shared_context.get("owner_sub_hypothesis_id"),
                    "admitted_source_ids": reused_source_ids,
                    "direct_primary_evidence_eligible": False,
                    "counts_toward_core_slot_readiness": False,
                },
            })
            diagnostic.update({
                "status": "reused_shared_foundational_context",
                "shared_context_key": shared_context_key,
                "shared_context_owner_sub_hypothesis_id": shared_context.get(
                    "owner_sub_hypothesis_id"
                ),
                "reused_source_count": len(reused_source_ids),
            })
            log_event(
                "SCIENCE",
            "v3_foundational_context_reused",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                research_question_task_id=task_id,
                shared_context_key=shared_context_key,
                owner_sub_hypothesis_id=shared_context.get("owner_sub_hypothesis_id"),
                reused_source_count=len(reused_source_ids),
            )
        elif (
            str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
            and reuse_verdict["verdict"] == "SATISFIED_BY_REUSE"
        ):
            reused_source_ids = list(dict.fromkeys(
                str(item.get("source_id") or "") for item in reusable_assertions if str(item.get("source_id") or "")
            ))
            reused_assertion_ids = list(dict.fromkeys(
                str(item.get("assertion_id") or "") for item in reusable_assertions if str(item.get("assertion_id") or "")
            ))
            result.update({
                "status": "REUSED_EXISTING_EVIDENCE",
                "source_ids": reused_source_ids,
                "reused_source_ids": reused_source_ids,
                "assertion_ids": reused_assertion_ids,
                "direct_slot_admitted_ids": [slot],
                "direct_slot_admitted_source_ids": reused_source_ids,
                "direct_slot_admitted_assertion_ids_by_slot": {slot: reused_assertion_ids},
                "direct_slot_admitted_source_ids_by_slot": {slot: reused_source_ids},
                "direct_slot_admitted_span_ids_by_slot": {slot: reuse_verdict["distinct_span_ids"]},
                "direct_slot_admitted_count": len(reused_source_ids),
                "reused_direct_slot_admitted_assertion_count": len(reused_assertion_ids),
                "reused_direct_slot_admitted_source_count": len(reused_source_ids),
                "coverage_bundle_id": reuse_verdict["coverage_bundle_id"],
                "coverage_bundle_kind": reuse_verdict["coverage_bundle_kind"],
                "comparison_signature": reuse_verdict["comparison_signature"],
                "comparison_coverage_bundle_ids": list(
                    reuse_verdict.get("comparison_coverage_bundle_ids") or []
                ),
                "comparison_target_pair_ids": list(
                    reuse_verdict.get("comparison_target_pair_ids") or []
                ),
                "comparison_direct_pair_ids": list(
                    reuse_verdict.get("comparison_direct_pair_ids") or []
                ),
                "comparison_missing_direct_pair_ids": list(
                    reuse_verdict.get("comparison_missing_direct_pair_ids") or []
                ),
                "direct_pair_coverage_complete": bool(
                    reuse_verdict.get("direct_pair_coverage_complete")
                ),
                "scientific_obligation_status": (
                    "ARM_EVIDENCE_READY"
                    if comparison_contract
                    else "SLOT_OBLIGATION_EVALUATED"
                ),
                "provider_dispatch_reason": "qualified_current_contract_slot_support_satisfies_reuse_policy",
            })
            diagnostic.update({
                "status": "reused_existing_slot_assertion",
                "reused_source_count": len(reused_source_ids),
                "reused_assertion_count": len(reused_assertion_ids),
            })
            log_event(
                "SCIENCE",
                "v3_retrieval_task_reused_existing_evidence",
                project_id=project_id,
                wave_index=wave,
                sub_hypothesis_id=sub_id,
                task_id=task_id,
                slot=diagnostic["slot"],
                reused_assertion_count=len(reused_assertion_ids),
                slot_policy_verdict=reuse_verdict["verdict"],
                provider_dispatch_status=reuse_verdict["provider_dispatch_status"],
                comparison_missing_direct_pair_ids=list(
                    reuse_verdict.get("comparison_missing_direct_pair_ids") or []
                ),
            )
        elif (
            isinstance(prior_result, dict)
            and not deferred_continuation_allowed
            and prior_outcome_reusable
        ):
            source_ids = list(dict.fromkeys(str(item) for item in prior_result.get("source_ids", []) if str(item)))
            result.update({
                "status": "REUSED_PRIOR_V3_TASK_OUTCOME",
                "source_ids": source_ids,
                "reused_source_ids": source_ids,
                "assertion_ids": list(dict.fromkeys(str(item) for item in prior_result.get("assertion_ids", []) if str(item))),
                "direct_slot_admitted_ids": list(dict.fromkeys(
                    str(item) for item in prior_result.get("direct_slot_admitted_ids", []) if str(item)
                )),
                "direct_slot_admitted_source_ids": list(dict.fromkeys(
                    str(item) for item in prior_result.get("direct_slot_admitted_source_ids", []) if str(item)
                )),
                "candidate_count": max(0, int(prior_result.get("candidate_count") or 0)),
                "metadata_kept_count": max(0, int(prior_result.get("metadata_kept_count") or 0)),
                "fulltext_available_count": max(0, int(prior_result.get("fulltext_available_count") or 0)),
                "alignment_completed_count": max(0, int(prior_result.get("alignment_completed_count") or 0)),
                "alignment_not_executed_count": max(0, int(prior_result.get("alignment_not_executed_count") or 0)),
                "alignment_integrity_error_count": max(0, int(prior_result.get("alignment_integrity_error_count") or 0)),
                "foundation_context_count": max(0, int(prior_result.get("foundation_context_count") or 0)),
                "background_only_count": max(0, int(prior_result.get("background_only_count") or 0)),
                "contract_rejected_count": max(0, int(prior_result.get("contract_rejected_count") or 0)),
                "raw_provider_result_count": max(0, int(prior_result.get("raw_provider_result_count") or 0)),
                "configured_providers": list(prior_result.get("configured_providers") or []),
                "dispatched_providers": list(prior_result.get("dispatched_providers") or []),
                "skipped_providers": list(prior_result.get("skipped_providers") or []),
                "deferred_provider_count": max(0, int(prior_result.get("deferred_provider_count") or 0)),
                "provider_error_count": max(0, int(prior_result.get("provider_error_count") or 0)),
                "provider_submission_count": max(
                    0, int(prior_result.get("provider_submission_count") or 0)
                ),
                "provider_terminal_response_count": max(
                    0, int(prior_result.get("provider_terminal_response_count") or 0)
                ),
                "local_query_compilation_rejection_count": max(
                    0, int(prior_result.get("local_query_compilation_rejection_count") or 0)
                ),
                "provider_continuation_attempts": max(
                    0, int(prior_result.get("provider_continuation_attempts") or 0)
                ),
                "query_variant_execution_v3": (
                    dict(prior_result.get("query_variant_execution_v3") or {})
                    if isinstance(prior_result.get("query_variant_execution_v3"), dict)
                    else {}
                ),
                "provider_outcomes_v3": [
                    dict(item)
                    for item in prior_result.get("provider_outcomes_v3", [])
                    if isinstance(item, dict)
                ],
                "provider_outcome_v3": (
                    dict(prior_result.get("provider_outcome_v3") or {})
                    if isinstance(prior_result.get("provider_outcome_v3"), dict)
                    else {}
                ),
                "candidate_pool_diagnostics": (
                    dict(prior_result.get("candidate_pool_diagnostics") or {})
                    if isinstance(prior_result.get("candidate_pool_diagnostics"), dict)
                    else {}
                ),
                "candidate_disposition": str(prior_result.get("candidate_disposition") or ""),
                "candidate_disposition_counts": (
                    dict(prior_result.get("candidate_disposition_counts") or {})
                    if isinstance(prior_result.get("candidate_disposition_counts"), dict)
                    else {}
                ),
            })
            diagnostic.update({
                "status": "reused_prior_v3_task_outcome",
                "reused_source_count": len(source_ids),
                "prior_task_status": str(prior_result.get("status") or ""),
                "reason": "retain the current V3 task outcome for the same plan revision",
            })
        elif isinstance(prior_result, dict) and not deferred_continuation_allowed:
            diagnostic.update({
                "prior_task_status": str(prior_result.get("status") or ""),
                "prior_outcome_policy_reuse": "rejected",
                "reason": "prior positive-task outcome remains underqualified under the current V3 slot policy",
            })
        elif not task_id or not query or not fingerprint:
            result["status"] = "INVALID_V3_TASK"
            diagnostic.update({"status": "invalid_v3_task", "coverage_status": "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY"})
        else:
            failure_stage = "query_compilation"
            try:
                search_payload: dict[str, Any]
                discovery_pool_key = "|".join(
                    (
                        str(context["contract"].get("contract_id") or ""),
                        str(
                            context["contract"].get("contract_revision")
                            or context["contract"].get("declaration_hash")
                            or ""
                        ),
                        str(task.get("query_mode") or "").upper(),
                        discovery_fingerprint,
                    )
                )
                shared_discovery_candidates: list[dict[str, Any]] = []
                shared_discovery_sources: list[dict[str, Any]] = []
                sh_discovery_state = context.get("sh_discovery_state")
                sh_batch_lead = False
                if str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT":
                    foundation_contract = task.get("foundation_context_contract") if isinstance(task.get("foundation_context_contract"), dict) else {}
                    foundation_contract = {
                        **foundation_contract,
                        "contract_revision": str(
                            context["contract"].get("contract_revision")
                            or context["contract"].get("declaration_hash")
                            or ""
                        ),
                    }
                    raw_search_payload = search_foundational_context_v3(
                        foundation_contract,
                        project_id=project_id,
                        project_discipline_taxonomy=project_taxonomy,
                        exclude_candidate_keys=set(context["seen_candidate_keys"]),
                        sub_hypothesis_id=sub_id,
                        query_branch=query_branch,
                        plan_revision=plan_revision,
                        research_question_task_id=task_id,
                        evidence_slot=str(
                            task.get("slot") or task.get("requirement") or ""
                        ),
                        query_fingerprint=fingerprint,
                        groupchat_id=str(groupchat_id or ""),
                        run_id=str(run_id or ""),
                        retrieval_wave_id=diagnostic["retrieval_wave_id"],
                        research_question_contract_id=str(
                            context["contract"].get("contract_id") or ""
                        ),
                        research_question_contract_hash=str(
                            context["contract"].get("declaration_hash")
                            or context["contract"].get("contract_revision")
                            or ""
                        ),
                        query_branch_id=query_branch,
                        query_branch_role=str(task.get("query_mode") or ""),
                    )
                    failure_stage = "search_payload_decode"
                    search_payload = decode_payload(raw_search_payload)
                    failure_stage = "search_artifact_load"
                    result["foundation_context_execution"] = dict(search_payload.get("foundation_retrieval") or {})
                else:
                    failure_stage = "query_compilation"
                    candidate_scope = slot_candidate_scope(
                        context["contract"],
                        spec,
                        sub_hypothesis_id=sub_id,
                        evidence_slot=slot_identity,
                        query_branch=query_branch,
                    )
                    sh_batch_lead = bool(
                        str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
                        and not targeted_gap_retrieval
                        and isinstance(sh_discovery_state, dict)
                        and str(sh_discovery_state.get("status") or "NOT_STARTED")
                        == "NOT_STARTED"
                    )
                    pool = context["raw_candidate_pool_by_discovery_fingerprint"].get(
                        discovery_pool_key
                    )
                    if isinstance(pool, dict):
                        pool_candidates = pool.get("candidates")
                        if isinstance(pool_candidates, list):
                            shared_discovery_candidates = [
                                dict(candidate)
                                for candidate in pool_candidates
                                if isinstance(candidate, dict)
                            ]
                        source_task_ids = pool.get("source_task_ids")
                        if isinstance(source_task_ids, list):
                            shared_discovery_sources = [
                                dict(item)
                                for item in source_task_ids
                                if isinstance(item, dict)
                            ]
                    explicit_provider_plan = {
                        **spec,
                        **(
                            {
                                "comparison_retrieval_phase_v4": dict(
                                    comparison_execution_phase
                                ),
                            }
                            if comparison_execution_phase
                            else {}
                        ),
                        "project_id": project_id,
                        "groupchat_id": str(groupchat_id or ""),
                        "run_id": str(run_id or ""),
                        "retrieval_wave_id": f"{groupchat_id or 'groupchat'}:{run_id or 'run'}:wave_{wave}",
                        "sub_hypothesis_id": sub_id,
                        "research_question_contract_id": str(
                            context["contract"].get("contract_id") or ""
                        ),
                        "research_question_contract_hash": str(
                            context["contract"].get("declaration_hash")
                            or context["contract"].get("contract_revision")
                            or ""
                        ),
                        "query": query,
                        "branch": query_branch,
                        "query_branch": query_branch,
                        "query_branch_id": query_branch,
                        "query_branch_role": str(task.get("query_mode") or ""),
                        "research_question_task_id": task_id,
                        "evidence_slot": str(
                            task.get("slot") or task.get("requirement") or ""
                        ),
                        "plan_revision": plan_revision,
                        "query_fingerprint": fingerprint,
                        "retrieval_obligation_v3": (
                            dict(task.get("retrieval_obligation_v3") or {})
                            if isinstance(task.get("retrieval_obligation_v3"), dict)
                            else {}
                        ),
                        "retrieval_work_item_v3": (
                            dict(task.get("retrieval_work_item_v3") or {})
                            if isinstance(task.get("retrieval_work_item_v3"), dict)
                            else {}
                        ),
                        "candidate_alignment_contract": candidate_scope,
                        "retrieval_anchor_contract": (
                            dict(spec.get("retrieval_anchor_contract") or {})
                            if isinstance(spec.get("retrieval_anchor_contract"), dict)
                            else {}
                        ),
                    }
                    provider_query_plans = [explicit_provider_plan]
                    if sh_batch_lead:
                        provider_query_plans = []
                        for batch_task in positive_by_context.get(sub_id, []):
                            batch_spec = (
                                batch_task.get("retrieval_spec_v3")
                                if isinstance(batch_task.get("retrieval_spec_v3"), dict)
                                else {}
                            )
                            batch_branch = str(
                                batch_spec.get("query_branch")
                                or batch_task.get("query_branch")
                                or f"{sub_id}:{batch_task.get('slot') or batch_task.get('requirement') or batch_task.get('task_id')}"
                            ).strip()
                            batch_scope = slot_candidate_scope(
                                context["contract"],
                                batch_spec,
                                sub_hypothesis_id=sub_id,
                                evidence_slot=str(
                                    batch_spec.get("slot_identity")
                                    or batch_task.get("slot")
                                    or batch_task.get("requirement")
                                    or ""
                                ),
                                query_branch=batch_branch,
                            )
                            provider_query_plans.append({
                                **batch_spec,
                                "project_id": project_id,
                                "groupchat_id": str(groupchat_id or ""),
                                "run_id": str(run_id or ""),
                                "retrieval_wave_id": str(
                                    sh_discovery_state.get("retrieval_wave_id")
                                    or diagnostic["retrieval_wave_id"]
                                ),
                                "sub_hypothesis_id": sub_id,
                                "research_question_contract_id": str(
                                    context["contract"].get("contract_id") or ""
                                ),
                                "research_question_contract_hash": str(
                                    context["contract"].get("declaration_hash")
                                    or context["contract"].get("contract_revision")
                                    or ""
                                ),
                                "query": str(batch_spec.get("provider_query") or ""),
                                "branch": batch_branch,
                                "query_branch": batch_branch,
                                "query_branch_id": batch_branch,
                                "query_branch_role": str(
                                    batch_task.get("query_mode") or "POSITIVE_EVIDENCE"
                                ),
                                "research_question_task_id": str(
                                    batch_task.get("task_id") or ""
                                ),
                                "evidence_slot": str(
                                    batch_task.get("slot")
                                    or batch_task.get("requirement")
                                    or ""
                                ),
                                "plan_revision": plan_revision,
                                "query_fingerprint": str(
                                    batch_spec.get("semantic_fingerprint") or ""
                                ),
                                "retrieval_obligation_v3": (
                                    dict(batch_task.get("retrieval_obligation_v3") or {})
                                    if isinstance(
                                        batch_task.get("retrieval_obligation_v3"),
                                        dict,
                                    )
                                    else {}
                                ),
                                "retrieval_obligations_v3": [
                                    dict(item)
                                    for item in batch_task.get(
                                        "retrieval_obligations_v3", []
                                    )
                                    if isinstance(item, dict)
                                ],
                                "retrieval_work_item_v3": (
                                    dict(batch_task.get("retrieval_work_item_v3") or {})
                                    if isinstance(
                                        batch_task.get("retrieval_work_item_v3"),
                                        dict,
                                    )
                                    else {}
                                ),
                                "candidate_alignment_contract": batch_scope,
                                "retrieval_anchor_contract": (
                                    dict(batch_spec.get("retrieval_anchor_contract") or {})
                                    if isinstance(batch_spec.get("retrieval_anchor_contract"), dict)
                                    else {}
                                ),
                                "sh_discovery_batch": True,
                            })
                        sh_discovery_state["status"] = "PROVIDER_BATCH_STARTED"
                        sh_discovery_state["retrieval_wave_id"] = diagnostic[
                            "retrieval_wave_id"
                        ]
                        log_event(
                            "SCIENCE",
                            "v3_sh_discovery_batch_started",
                            project_id=project_id,
                            sub_hypothesis_id=sub_id,
                            query_branch_count=len(provider_query_plans),
                            retrieval_wave_id=diagnostic["retrieval_wave_id"],
                            layer_quotas=dict(DEFAULT_SH_LAYER_QUOTAS),
                        )
                    elif (
                        isinstance(sh_discovery_state, dict)
                        and str(sh_discovery_state.get("status") or "")
                        in {"PROVIDER_BATCH_READY", "COMPLETED"}
                    ):
                        shared_discovery_candidates = [
                            dict(candidate)
                            for candidate in sh_discovery_state.get("candidate_pool", [])
                            if isinstance(candidate, dict)
                        ]
                    validate_provider_query_plans(provider_query_plans)
                    raw_search_payload = search_papers_stratified(
                        query,
                        databases=providers,
                        max_results=(
                            sum(DEFAULT_SH_LAYER_QUOTAS.values())
                            if sh_batch_lead
                            else int(profile.get("candidate_budget") or 0)
                        ),
                        domain=str(project.get("domain") or ""),
                        focus_branches=[],
                        explicit_query_plan=provider_query_plans,
                        use_llm=use_llm,
                        layer_quotas=(
                            dict(DEFAULT_SH_LAYER_QUOTAS)
                            if sh_batch_lead
                            else dict(profile.get("layer_quotas") or {})
                        ),
                        project_discipline_taxonomy=project_taxonomy,
                        research_question_card=context["contract"],
                        single_paper_serial=True,
                        project_id=project_id,
                        sub_hypothesis_id=sub_id,
                        retrieval_scope_kind="subhypothesis",
                        alignment_contract_hash=str(
                            context["contract"].get("declaration_hash")
                            or context["contract"].get("contract_revision")
                            or context["contract"].get("contract_id")
                            or ""
                        ),
                        candidate_alignment_contract=(
                            context.get("sh_candidate_scope")
                            if sh_batch_lead
                            else candidate_scope
                        ),
                        retrieval_anchor_contract=(
                            None
                            if sh_batch_lead
                            else dict(spec.get("retrieval_anchor_contract") or {})
                            if isinstance(spec.get("retrieval_anchor_contract"), dict)
                            else None
                        ),
                        exclude_candidate_keys=set(context["seen_candidate_keys"]),
                        previously_imported_source_count=len(
                            context["imported_source_ids_set"]
                        ),
                        v3_provider_allowlist=(
                            deferred_continuation_providers
                            if deferred_continuation_allowed
                            else None
                        ),
                        v3_prior_provider_execution=(
                            deferred_continuation_execution
                            if deferred_continuation_allowed
                            else None
                        ),
                        shared_raw_candidate_pool=(
                            [] if targeted_gap_retrieval else shared_discovery_candidates
                        ),
                        shared_raw_candidate_pool_only=(
                            not targeted_gap_retrieval
                            and not sh_batch_lead
                            and isinstance(sh_discovery_state, dict)
                            and str(sh_discovery_state.get("status") or "")
                            in {"PROVIDER_BATCH_READY", "COMPLETED"}
                        ),
                    )
                    failure_stage = "search_payload_decode"
                    search_payload = decode_payload(raw_search_payload)
                    failure_stage = "search_artifact_load"
                    search_id = str(search_payload.get("search_id") or "").strip()
                    search_artifact = load_search(search_id) if search_id else {}
                    provider_candidates = [
                        candidate
                        for candidate in flatten_literature_results(
                            [
                                block
                                for block in search_artifact.get("provider_blocks", [])
                                if isinstance(block, dict)
                            ]
                        )
                        if isinstance(candidate, dict)
                    ]
                    if provider_candidates:
                        pool = context["raw_candidate_pool_by_discovery_fingerprint"].setdefault(
                            discovery_pool_key,
                            {
                                "schema_version": "v3_raw_candidate_discovery_pool_v1",
                                "discovery_fingerprint": discovery_fingerprint,
                                "query_mode": str(task.get("query_mode") or "").upper(),
                                "candidates": [],
                                "source_task_ids": [],
                            },
                        )
                        existing_candidates = (
                            pool.get("candidates")
                            if isinstance(pool.get("candidates"), list)
                            else []
                        )
                        candidates_by_key = {
                            str(literature_result_unique_key(candidate) or "").strip(): candidate
                            for candidate in existing_candidates
                            if isinstance(candidate, dict)
                            and str(literature_result_unique_key(candidate) or "").strip()
                        }
                        source_task = {
                            "task_id": task_id,
                            "query_branch": query_branch,
                            "query_fingerprint": fingerprint,
                        }
                        for candidate in provider_candidates:
                            candidate_key = str(
                                literature_result_unique_key(candidate) or ""
                            ).strip()
                            if candidate_key and candidate_key not in candidates_by_key:
                                pooled_candidate = dict(candidate)
                                pooled_candidate["candidate_discovery_provenance"] = {
                                    "mode": "provider_raw_discovery",
                                    "discovery_fingerprint": discovery_fingerprint,
                                    "source_task": dict(source_task),
                                }
                                candidates_by_key[candidate_key] = pooled_candidate
                        pool["candidates"] = list(candidates_by_key.values())
                        source_task_ids = pool.setdefault("source_task_ids", [])
                        if source_task not in source_task_ids:
                            source_task_ids.append(source_task)
                        retrieval_run_context[
                            "raw_candidate_pool_by_discovery_fingerprint"
                        ][discovery_pool_key] = {
                            "schema_version": "v3_raw_candidate_discovery_pool_audit_v1",
                            "discovery_fingerprint": discovery_fingerprint,
                            "query_mode": str(task.get("query_mode") or "").upper(),
                            "candidate_count": len(pool["candidates"]),
                            "source_task_ids": sorted({
                                str(item.get("task_id") or "")
                                for item in source_task_ids
                                if isinstance(item, dict)
                                and str(item.get("task_id") or "")
                            }),
                            "slot_completion_inferred": False,
                        }
                context["search_count"] += 1
                search_id = str(search_payload.get("search_id") or "").strip()
                candidates = [
                    candidate
                    for candidate in search_payload.get("results", [])
                    if isinstance(candidate, dict)
                ]
                if sh_batch_lead and isinstance(sh_discovery_state, dict):
                    selection = select_sh_paper_quota(
                        candidates,
                        quotas=DEFAULT_SH_LAYER_QUOTAS,
                        key_fn=literature_result_unique_key,
                    )
                    selected_pool = [
                        dict(item)
                        for item in selection.get("selected", [])
                        if isinstance(item, dict)
                    ]
                    sh_discovery_state.update({
                        "status": "PROVIDER_BATCH_READY",
                        "candidate_pool": selected_pool,
                        "selected_corpus": selection,
                        "provider_search_id": str(search_payload.get("search_id") or ""),
                    })
                    context["sh_run"].update({
                        "status": "CANDIDATE_CORPUS_SELECTED",
                        "candidate_pool": [dict(item) for item in candidates],
                        "selected_corpus": dict(selection),
                        "provider_diagnostics": dict(
                            search_payload.get("query_variant_execution_v3") or {}
                        ),
                    })
                    # The lead task consumes the same bounded corpus that every
                    # other task in this SH will inspect.  The source records
                    # remain task-scoped during evidence alignment.
                    candidates = selected_pool
                    result["sh_discovery_batch"] = {
                        "schema_version": "sh_discovery_batch_result_v1",
                        "branch_count": int(
                            context["sh_query_plan"].get("branch_count") or 0
                        ),
                        "selected_count": len(selected_pool),
                        "selected_by_layer": dict(
                            selection.get("selected_by_layer") or {}
                        ),
                        "duplicate_count": int(selection.get("duplicate_count") or 0),
                    }
                    log_event(
                        "SCIENCE",
                        "v3_sh_discovery_batch_completed",
                        project_id=project_id,
                        sub_hypothesis_id=sub_id,
                        query_branch_count=int(
                            context["sh_query_plan"].get("branch_count") or 0
                        ),
                        selected_count=len(selected_pool),
                        selected_by_layer=dict(selection.get("selected_by_layer") or {}),
                        duplicate_count=int(selection.get("duplicate_count") or 0),
                    )
                if shared_discovery_candidates:
                    pool_diagnostics = (
                        search_payload.get("candidate_pool_diagnostics")
                        if isinstance(search_payload.get("candidate_pool_diagnostics"), dict)
                        else {}
                    )
                    result["raw_candidate_pool_provenance"] = {
                        "mode": "shared_candidate_discovery",
                        "discovery_fingerprint": discovery_fingerprint,
                        "source_task_ids": shared_discovery_sources,
                        "available_candidate_count": len(shared_discovery_candidates),
                        "preprint_excluded_count": int(
                            pool_diagnostics.get(
                                "shared_raw_candidate_pool_preprint_excluded_count"
                            ) or 0
                        ),
                        "selected_for_current_slot_count": int(
                            pool_diagnostics.get(
                                "shared_raw_candidate_pool_selected_count"
                            ) or 0
                        ),
                        "selection_policy": str(
                            pool_diagnostics.get("shared_raw_candidate_pool_policy")
                            or "raw_metadata_reenters_current_slot_layer_domain_and_fulltext_gates"
                        ),
                        "slot_completion_inferred": False,
                    }
                    log_event(
                        "SCIENCE",
                        "v3_raw_candidate_pool_reused",
                        project_id=project_id,
                        sub_hypothesis_id=sub_id,
                        research_question_task_id=task_id,
                        evidence_slot=diagnostic["slot"],
                        query_branch=query_branch,
                        discovery_fingerprint=discovery_fingerprint,
                        available_candidate_count=len(shared_discovery_candidates),
                        preprint_excluded_count=int(
                            pool_diagnostics.get(
                                "shared_raw_candidate_pool_preprint_excluded_count"
                            ) or 0
                        ),
                        selected_for_current_slot_count=int(
                            pool_diagnostics.get(
                                "shared_raw_candidate_pool_selected_count"
                            ) or 0
                        ),
                        selection_policy=str(
                            pool_diagnostics.get("shared_raw_candidate_pool_policy")
                            or "raw_metadata_reenters_current_slot_layer_domain_and_fulltext_gates"
                        ),
                        slot_completion_inferred=False,
                    )
                variant_execution = (
                    dict(search_payload.get("query_variant_execution_v3") or {})
                    if isinstance(search_payload.get("query_variant_execution_v3"), dict)
                    else {}
                )
                result["query_variant_execution_v3"] = variant_execution
                if isinstance(
                    variant_execution.get("comparison_retrieval_phase_v4"), dict
                ):
                    result["comparison_retrieval_phase_v4"] = dict(
                        variant_execution["comparison_retrieval_phase_v4"]
                    )
                provider_outcomes_v3 = [
                    dict(item)
                    for item in variant_execution.get("provider_outcomes", [])
                    if isinstance(item, dict)
                ]
                result["provider_outcomes_v3"] = provider_outcomes_v3
                result["provider_outcome_v3"] = (
                    dict(provider_outcomes_v3[-1]) if provider_outcomes_v3 else {}
                )
                if deferred_continuation_allowed:
                    variant_execution["continuation"] = {
                        "attempt": result["provider_continuation_attempts"],
                        "providers": list(deferred_continuation_providers),
                        "reused_prior_semantic_attempts": True,
                    }
                result["raw_provider_result_count"] = max(
                    0, int(variant_execution.get("raw_provider_result_count") or 0)
                )
                result["configured_providers"] = list(
                    variant_execution.get("configured_providers")
                    or search_payload.get("configured_providers")
                    or []
                )
                result["dispatched_providers"] = list(
                    variant_execution.get("dispatched_providers")
                    or search_payload.get("dispatched_providers")
                    or []
                )
                result["skipped_providers"] = list(
                    variant_execution.get("skipped_providers")
                    or search_payload.get("skipped_providers")
                    or []
                )
                result["deferred_provider_count"] = len(
                    variant_execution.get("deferred_providers") or []
                )
                result["provider_error_count"] = max(
                    0, int(variant_execution.get("provider_error_count") or 0)
                )
                result["provider_submission_count"] = max(
                    0, int(variant_execution.get("provider_submission_count") or 0)
                )
                result["provider_terminal_response_count"] = max(
                    0, int(variant_execution.get("provider_terminal_response_count") or 0)
                )
                result["local_query_compilation_rejection_count"] = max(
                    0, int(variant_execution.get("local_compilation_rejection_count") or 0)
                )
                result["candidate_count"] += len(candidates)
                diagnostic.update({
                    "status": "searched",
                    "search_id": search_id,
                    "result_count": len(candidates),
                    "incoming_excluded_candidate_key_count": int(search_payload.get("incoming_excluded_candidate_key_count") or len(context["seen_candidate_keys"])),
                    "cross_task_duplicates_excluded": int(search_payload.get("cross_task_duplicates_excluded") or 0),
                    "provider_candidates_before_cross_task_dedup": int(
                        search_payload.get("provider_candidates_before_cross_task_dedup")
                        or len(candidates)
                    ),
                    "removed_as_previously_seen": int(
                        search_payload.get("removed_as_previously_seen") or 0
                    ),
                    "new_candidate_count": int(
                        search_payload.get("new_candidate_count") or len(candidates)
                    ),
                    "previously_imported_source_count": int(
                        search_payload.get("previously_imported_source_count")
                        or len(context["imported_source_ids_set"])
                    ),
                    "query_variant_execution_v3": variant_execution,
                    "provider_outcomes_v3": provider_outcomes_v3,
                    "raw_provider_result_count": result["raw_provider_result_count"],
                    "configured_providers": result["configured_providers"],
                    "dispatched_providers": result["dispatched_providers"],
                    "skipped_providers": result["skipped_providers"],
                })
                if search_id:
                    import_limit = min(len(candidates), int(profile.get("candidate_budget") or len(candidates)))
                    selected_candidates: list[dict[str, Any]] = []
                    for candidate in candidates[:import_limit]:
                        candidate_key = str(literature_result_unique_key(candidate) or "").strip()
                        if candidate_key and candidate_key in context["seen_candidate_keys"]:
                            diagnostic["cross_task_duplicates_skipped_before_import"] = int(diagnostic.get("cross_task_duplicates_skipped_before_import") or 0) + 1
                            continue
                        selected = dict(candidate)
                        selected["_v3_candidate_key"] = candidate_key
                        selected_candidates.append(selected)
                        if candidate_key:
                            context["seen_candidate_keys"].add(candidate_key)
                    import_contract = {
                        **bind_research_question_task_scope(
                            context["contract"],
                            {
                                "task_id": task_id,
                                "object_scope": dict(task.get("object_scope") or {}),
                                "target_slot_ids": list(
                                    task.get("target_slot_ids") or [
                                        task.get("slot") or task.get("requirement") or ""
                                    ]
                                ),
                            },
                        ),
                        "groupchat_id": str(groupchat_id or ""),
                        "run_id": str(run_id or ""),
                        "retrieval_wave_id": f"{groupchat_id or 'groupchat'}:{run_id or 'run'}:wave_{wave}",
                        "research_question_task_id": task_id,
                        "evidence_slot": str(
                            task.get("slot") or task.get("requirement") or ""
                        ),
                        "plan_revision": plan_revision,
                        "query_branch_id": query_branch,
                        "query_branch_role": str(task.get("query_mode") or ""),
                    }
                    sh_alignment_contracts: list[dict[str, Any]] = []
                    if sh_batch_lead:
                        for batch_task in positive_by_context.get(sub_id, []):
                            batch_task_id = str(batch_task.get("task_id") or "")
                            batch_slot = str(
                                batch_task.get("slot")
                                or batch_task.get("requirement")
                                or ""
                            )
                            batch_contract = {
                                **bind_research_question_task_scope(
                                    context["contract"],
                                    {
                                        "task_id": batch_task_id,
                                        "object_scope": dict(
                                            batch_task.get("object_scope") or {}
                                        ),
                                        "target_slot_ids": list(
                                            batch_task.get("target_slot_ids") or [batch_slot]
                                        ),
                                    },
                                ),
                                "groupchat_id": str(groupchat_id or ""),
                                "run_id": str(run_id or ""),
                                "retrieval_wave_id": str(
                                    sh_discovery_state.get("retrieval_wave_id")
                                    or diagnostic["retrieval_wave_id"]
                                ),
                                "research_question_task_id": batch_task_id,
                                "evidence_slot": batch_slot,
                                "plan_revision": plan_revision,
                                "query_branch": str(
                                    (
                                        batch_task.get("retrieval_spec_v3")
                                        if isinstance(batch_task.get("retrieval_spec_v3"), dict)
                                        else {}
                                    ).get("query_branch")
                                    or batch_task.get("query_branch")
                                    or f"{sub_id}:{batch_slot}"
                                ),
                                "query_branch_role": str(
                                    batch_task.get("query_mode") or "POSITIVE_EVIDENCE"
                                ),
                            }
                            sh_alignment_contracts.append(batch_contract)
                    failure_stage = "search_artifact_load"
                    search_record = load_search(search_id)
                    prepared_batches: list[dict[str, Any]] = []
                    commit_batches: list[dict[str, Any]] = []
                    for batch_start in range(
                        0,
                        len(selected_candidates),
                        FULLTEXT_PREPARE_BATCH_SIZE,
                    ):
                        candidate_batch = selected_candidates[
                            batch_start:batch_start + FULLTEXT_PREPARE_BATCH_SIZE
                        ]
                        failure_stage = "candidate_preparation"
                        prepared_batch = prepare_v3_literature_candidate_batch(
                            project=project,
                            search_record=search_record,
                            candidates=candidate_batch,
                            project_id=project_id,
                            search_id=search_id,
                            use_llm=use_llm,
                            query_branch_override=query_branch,
                            alignment_contract=import_contract,
                            alignment_contracts=(
                                sh_alignment_contracts
                                if sh_batch_lead
                                else None
                            ),
                            evidence_kind_override=(
                                "foundational_context"
                                if str(task.get("query_mode") or "").upper()
                                == "FOUNDATIONAL_CONTEXT"
                                else ""
                            ),
                        )
                        prepared_batches.append(prepared_batch)
                        failure_stage = "candidate_commit"
                        commit_batches.append(
                            commit_v3_prepared_literature_candidate_batch(
                                prepared_batch,
                                project=project,
                                save_project_callback=save_project,
                            )
                        )
                    prepared_summary = {
                        "schema_version": "v3_prepared_literature_candidate_batches_v1",
                        "batch_count": len(prepared_batches),
                        "requested_count": sum(
                            int(batch.get("requested_count") or 0)
                            for batch in prepared_batches
                        ),
                        "prepared_count": sum(
                            int(batch.get("prepared_count") or 0)
                            for batch in prepared_batches
                        ),
                        "terminal_count": sum(
                            int(batch.get("terminal_count") or 0)
                            for batch in prepared_batches
                        ),
                        "failed_count": sum(
                            int(batch.get("failed_count") or 0)
                            for batch in prepared_batches
                        ),
                        "max_workers": max(
                            (int(batch.get("max_workers") or 0) for batch in prepared_batches),
                            default=0,
                        ),
                        "elapsed_ms": round(
                            sum(float(batch.get("elapsed_ms") or 0.0) for batch in prepared_batches),
                            2,
                        ),
                    }
                    commit_summary = {
                        "schema_version": "v3_prepared_literature_candidate_commits_v1",
                        "batch_count": len(commit_batches),
                        "committed_count": sum(
                            int(batch.get("committed_count") or 0)
                            for batch in commit_batches
                        ),
                        "terminal_count": sum(
                            int(batch.get("terminal_count") or 0)
                            for batch in commit_batches
                        ),
                        "failed_count": sum(
                            int(batch.get("failed_count") or 0)
                            for batch in commit_batches
                        ),
                        "persist_count": sum(
                            int(batch.get("persist_count") or 0)
                            for batch in commit_batches
                        ),
                        "elapsed_ms": round(
                            sum(float(batch.get("elapsed_ms") or 0.0) for batch in commit_batches),
                            2,
                        ),
                    }
                    diagnostic["candidate_preparation"] = {
                        key: prepared_summary.get(key)
                        for key in (
                            "schema_version",
                            "batch_count",
                            "requested_count",
                            "prepared_count",
                            "terminal_count",
                            "failed_count",
                            "reused_fulltext_count",
                            "fulltext_available_count",
                            "llm_structured_count",
                            "max_workers",
                            "elapsed_ms",
                        )
                    }
                    diagnostic["candidate_commit"] = {
                        key: commit_summary.get(key)
                        for key in (
                            "schema_version",
                            "batch_count",
                            "committed_count",
                            "terminal_count",
                            "failed_count",
                            "persist_count",
                            "elapsed_ms",
                        )
                    }
                    failure_stage = "evidence_binding"
                    committed_items = [
                        committed_item
                        for batch in commit_batches
                        for committed_item in batch.get("results", [])
                        if isinstance(committed_item, dict)
                    ]
                    for committed_item in committed_items:
                        if not isinstance(committed_item, dict):
                            continue
                        if str(committed_item.get("status") or "") in {
                            "failed",
                            "commit_failed",
                        }:
                            diagnostic.setdefault("import_errors", []).append(
                                str(committed_item.get("error") or "candidate preparation or commit failed")[:180]
                            )
                            continue
                        imported = (
                            dict(committed_item.get("imported") or {})
                            if isinstance(committed_item.get("imported"), dict)
                            else {}
                        )
                        record = (
                            imported.get("record")
                            if isinstance(imported.get("record"), dict)
                            else imported.get("existing_record")
                            if isinstance(imported.get("existing_record"), dict)
                            else {}
                        )
                        source_id = str(record.get("paper_id") or "").strip()
                        if not source_id:
                            continue
                        if sh_batch_lead or targeted_gap_retrieval:
                            context["sh_committed_records"][source_id] = dict(record)
                        result["metadata_kept_count"] += 1
                        acquisition = (
                            record.get("full_text_acquisition")
                            if isinstance(record.get("full_text_acquisition"), dict)
                            else {}
                        )
                        if (
                            acquisition.get("available") is True
                            or len(str(record.get("full_text_excerpt") or "").strip()) >= 500
                        ):
                            result["fulltext_available_count"] += 1
                        contract_state = v3_contract_binding_state(
                            record,
                            context["contract"],
                            task_id,
                        )
                        if comparison_contract:
                            source_diagnostics = (
                                contract_state["admission"].get(
                                    "comparison_obligation_diagnostics"
                                )
                                if isinstance(contract_state.get("admission"), dict)
                                else {}
                            )
                            for candidate_diagnostic in (
                                source_diagnostics.get("candidate_diagnostics") or []
                                if isinstance(source_diagnostics, dict)
                                else []
                            ):
                                if not isinstance(candidate_diagnostic, dict):
                                    continue
                                diagnostic_entry = {
                                    "source_id": source_id,
                                    **dict(candidate_diagnostic),
                                }
                                if (
                                    diagnostic_entry
                                    not in result["comparison_candidate_diagnostics"]
                                ):
                                    result["comparison_candidate_diagnostics"].append(
                                        diagnostic_entry
                                    )
                        task_alignment = contract_state["task_alignment"]
                        task_alignment_status = str(
                            task_alignment.get("status") or ""
                        ).upper()
                        slot_statuses = (
                            task_alignment.get("slot_status")
                            if isinstance(task_alignment.get("slot_status"), dict)
                            else {}
                        )
                        target_slot_status = slot_statuses.get(
                            str(task.get("slot") or "").strip()
                        )
                        target_slot_status = (
                            target_slot_status
                            if isinstance(target_slot_status, dict)
                            else {}
                        )
                        result["target_slot_terminal_positive_count"] += len(
                            target_slot_status.get("terminal_positive_pair_ids") or []
                        )
                        result["target_slot_pending_pair_count"] += len(
                            target_slot_status.get("pending_pair_ids") or []
                        )
                        if task_alignment_status not in {"", "NOT_EXECUTED", "TASK_SCOPE_INVALID"}:
                            result["alignment_completed_count"] += 1
                        else:
                            result["alignment_not_executed_count"] += 1
                            if not contract_state["task_admission_found"]:
                                result["alignment_integrity_error_count"] += 1
                        if str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT":
                            result["foundation_context_count"] += 1
                        elif contract_state["admission"].get("direct_evidence_eligible") is True:
                            result["direct_slot_admitted_count"] += 1
                        elif contract_state["admission"].get("corpus_admitted") is True:
                            result["background_only_count"] += 1
                        elif contract_state["task_admission_found"]:
                            result["contract_rejected_count"] += 1
                        assertion_ids = record.get("evidence_assertion_ids") if isinstance(record.get("evidence_assertion_ids"), list) else []
                        imported_assertions = (
                            list(record.get("evidence_assertions_v4") or [])
                            if isinstance(record.get("evidence_assertions_v4"), list)
                            else []
                        )
                        if not imported_assertions and evidence_reader is not None:
                            for assertion_id in assertion_ids:
                                try:
                                    assertion = evidence_reader.get_evidence_assertion(
                                        project_id, str(assertion_id)
                                    )
                                except Exception:
                                    continue
                                if isinstance(assertion, dict):
                                    imported_assertions.append(assertion)
                        for assertion in imported_assertions:
                            if (
                                not isinstance(assertion, dict)
                                or str(assertion.get("research_question_contract_id") or "")
                                != str(context["contract"].get("contract_id") or "")
                            ):
                                continue
                            assertion_id = str(assertion.get("assertion_id") or "").strip()
                            assertion_task_id = str(
                                assertion.get("research_question_task_id") or ""
                            ).strip()
                            if assertion_task_id != task_id:
                                continue
                            for support in assertion.get("slot_support", []):
                                if not isinstance(support, dict):
                                    continue
                                covered_slot = str(support.get("slot_id") or "").strip()
                                if (
                                    covered_slot != str(task.get("slot") or "").strip()
                                    or not is_reusable_direct_slot_assertion(
                                    assertion,
                                    record,
                                    context["contract"],
                                    task_id,
                                    covered_slot,
                                )
                                ):
                                    continue
                                if covered_slot and covered_slot not in result["direct_slot_admitted_ids"]:
                                    result["direct_slot_admitted_ids"].append(covered_slot)
                                if source_id and source_id not in result["direct_slot_admitted_source_ids"]:
                                    result["direct_slot_admitted_source_ids"].append(source_id)
                                asserted_ids = result["direct_slot_admitted_assertion_ids_by_slot"].setdefault(
                                    covered_slot, []
                                )
                                if assertion_id and assertion_id not in asserted_ids:
                                    asserted_ids.append(assertion_id)
                                source_ids_by_slot = result["direct_slot_admitted_source_ids_by_slot"].setdefault(
                                    covered_slot, []
                                )
                                if source_id and source_id not in source_ids_by_slot:
                                    source_ids_by_slot.append(source_id)
                                span_ids_by_slot = result["direct_slot_admitted_span_ids_by_slot"].setdefault(
                                    covered_slot, []
                                )
                                for source_span_id in support.get("source_span_ids", []):
                                    source_span_id = str(source_span_id or "")
                                    if source_span_id and source_span_id not in span_ids_by_slot:
                                        span_ids_by_slot.append(source_span_id)
                                reusable = context["reusable_assertions_by_slot"].setdefault(
                                    task_slot_key(assertion_task_id, covered_slot), []
                                )
                                coverage_bundle = next(
                                    (
                                        bundle
                                        for bundle in contract_state["admission"].get("coverage_bundles", [])
                                        if isinstance(bundle, dict)
                                        and assertion_id in list(
                                            bundle.get("participating_assertion_ids") or []
                                        )
                                    ),
                                    {},
                                )
                                reusable_item = {
                                    "source_id": source_id,
                                    "assertion_id": assertion_id,
                                    "source_span_ids": list(support.get("source_span_ids") or []),
                                    "paper_id": str(support.get("paper_id") or source_id),
                                    "document_version_hash": str(
                                        support.get("document_version_hash")
                                        or assertion.get("document_version_hash")
                                        or ""
                                    ),
                                    "coverage_bundle_id": str(
                                        coverage_bundle.get("coverage_bundle_id") or ""
                                    ),
                                    "coverage_bundle_kind": str(
                                        coverage_bundle.get("bundle_id") or ""
                                    ),
                                    "comparison_signature": str(
                                        coverage_bundle.get("comparison_signature") or ""
                                    ),
                                    "comparison_contract_id": str(
                                        coverage_bundle.get("comparison_contract_id") or ""
                                    ),
                                    "direct_pair_id": str(
                                        coverage_bundle.get("direct_pair_id") or ""
                                    ),
                                }
                                if reusable_item not in reusable:
                                    reusable.append(reusable_item)
                        duplicate_reuse = str(imported.get("status") or "").lower() == "duplicate"
                        if duplicate_reuse or source_id in context["imported_source_ids_set"]:
                            if source_id not in result["reused_source_ids"]:
                                result["reused_source_ids"].append(source_id)
                        else:
                            context["imported_source_ids_set"].add(source_id)
                            context["imported_source_ids"].append(source_id)
                            result["new_source_ids"].append(source_id)
                        if source_id not in result["source_ids"]:
                            result["source_ids"].append(source_id)
                        for assertion_id in assertion_ids:
                            value = str(assertion_id or "").strip()
                            if value and value not in result["assertion_ids"]:
                                result["assertion_ids"].append(value)
                        if str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT":
                            foundation_admission = (
                                dict(record.get("foundation_context_admission") or {})
                                if isinstance(record.get("foundation_context_admission"), dict)
                                else {}
                            )
                            foundation_execution = result.setdefault(
                                "foundation_context_execution", {}
                            )
                            admitted_source_ids = foundation_execution.setdefault(
                                "admitted_source_ids", []
                            )
                            if foundation_admission.get("admitted") and source_id not in admitted_source_ids:
                                admitted_source_ids.append(source_id)
                            foundation_execution["l1_admitted_count"] = len(
                                admitted_source_ids
                            )
                            foundation_execution["status"] = str(
                                foundation_admission.get("status")
                                or foundation_execution.get("status")
                                or "PENDING_V3_CONTEXT_ADMISSION"
                            )
                            foundation_execution["direct_primary_evidence_eligible"] = False
                            foundation_execution["counts_toward_core_slot_readiness"] = False
                if (
                    not sh_batch_lead
                    and str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
                    and context.get("sh_committed_records")
                ):
                    # The SH lead reviewed each selected paper against every
                    # task-local contract.  Later branches consume those
                    # persisted task bindings instead of re-running PDF and
                    # proposition extraction for the same paper.
                    for source_id, committed_record in context[
                        "sh_committed_records"
                    ].items():
                        if not isinstance(committed_record, dict):
                            continue
                        imported_assertions = [
                            dict(item)
                            for item in committed_record.get(
                                "evidence_assertions_v4", []
                            )
                            if isinstance(item, dict)
                            and str(item.get("research_question_task_id") or "")
                            == task_id
                        ]
                        if not imported_assertions and evidence_reader is not None:
                            assertion_ids = (
                                committed_record.get("evidence_assertion_ids")
                                if isinstance(
                                    committed_record.get("evidence_assertion_ids"),
                                    list,
                                )
                                else (
                                    committed_record.get("evidence_storage_v4", {})
                                    .get("assertion_ids", [])
                                    if isinstance(
                                        committed_record.get("evidence_storage_v4"),
                                        dict,
                                    )
                                    else []
                                )
                            )
                            for assertion_id in assertion_ids:
                                try:
                                    assertion = evidence_reader.get_evidence_assertion(
                                        project_id, str(assertion_id)
                                    )
                                except Exception:
                                    continue
                                if (
                                    isinstance(assertion, dict)
                                    and str(
                                        assertion.get("research_question_task_id") or ""
                                    )
                                    == task_id
                                ):
                                    imported_assertions.append(assertion)
                        if not imported_assertions:
                            continue
                        if source_id not in result["source_ids"]:
                            result["source_ids"].append(source_id)
                        if source_id not in result["reused_source_ids"]:
                            result["reused_source_ids"].append(source_id)
                        result["metadata_kept_count"] += 1
                        result["alignment_completed_count"] += 1
                        for assertion in imported_assertions:
                            assertion_id = str(assertion.get("assertion_id") or "")
                            if assertion_id and assertion_id not in result["assertion_ids"]:
                                result["assertion_ids"].append(assertion_id)
                            for support in assertion.get("slot_support", []):
                                if not isinstance(support, dict):
                                    continue
                                covered_slot = str(support.get("slot_id") or "").strip()
                                if not covered_slot or not is_reusable_direct_slot_assertion(
                                    assertion,
                                    committed_record,
                                    context["contract"],
                                    task_id,
                                    covered_slot,
                                ):
                                    continue
                                reusable = context["reusable_assertions_by_slot"].setdefault(
                                    task_slot_key(task_id, covered_slot), []
                                )
                                reusable_item = {
                                    "source_id": source_id,
                                    "assertion_id": assertion_id,
                                    "source_span_ids": list(
                                        support.get("source_span_ids") or []
                                    ),
                                    "paper_id": str(
                                        support.get("paper_id") or source_id
                                    ),
                                    "document_version_hash": str(
                                        support.get("document_version_hash")
                                        or assertion.get("document_version_hash")
                                        or ""
                                    ),
                                }
                                if reusable_item not in reusable:
                                    reusable.append(reusable_item)
                                if source_id not in result["direct_slot_admitted_source_ids"]:
                                    result["direct_slot_admitted_source_ids"].append(source_id)
                                if assertion_id not in result["direct_slot_admitted_ids"]:
                                    result["direct_slot_admitted_ids"].append(assertion_id)
                                source_ids_by_slot = result[
                                    "direct_slot_admitted_source_ids_by_slot"
                                ].setdefault(covered_slot, [])
                                if source_id not in source_ids_by_slot:
                                    source_ids_by_slot.append(source_id)
                                span_ids_by_slot = result[
                                    "direct_slot_admitted_span_ids_by_slot"
                                ].setdefault(covered_slot, [])
                                for span_id in support.get("source_span_ids") or []:
                                    span_id = str(span_id or "")
                                    if span_id and span_id not in span_ids_by_slot:
                                        span_ids_by_slot.append(span_id)
                result["direct_slot_admitted_count"] = len(result["direct_slot_admitted_source_ids"])
                task_slot_admitted = diagnostic["slot"] in set(
                    result["direct_slot_admitted_ids"]
                )
                current_slot_supports = context["reusable_assertions_by_slot"].get(
                    task_slot_key(task_id, str(task.get("slot") or "")), []
                )
                current_reuse_verdict = slot_reuse_verdict(
                    task, current_slot_supports, context["contract"]
                )
                result["slot_policy_verdict"] = (
                    "SATISFIED_BY_NEW_EVIDENCE"
                    if task_slot_admitted
                    and current_reuse_verdict["verdict"] == "SATISFIED_BY_REUSE"
                    else current_reuse_verdict["verdict"]
                )
                shared_pool_reuse = bool(
                    not sh_batch_lead
                    and str(task.get("query_mode") or "").upper()
                    == "POSITIVE_EVIDENCE"
                    and isinstance(sh_discovery_state, dict)
                    and str(sh_discovery_state.get("status") or "")
                    in {"PROVIDER_BATCH_READY", "COMPLETED"}
                )
                result["provider_dispatch_status"] = (
                    "SHARED_DISCOVERY_POOL_REUSED"
                    if shared_pool_reuse
                    else "PROVIDER_DISPATCHED"
                )
                result["provider_dispatch_reason"] = (
                    "reuse_one_sh_discovery_batch_without_provider_dispatch"
                    if shared_pool_reuse
                    else (
                        "new_or_reaudited_source_bound_slot_support_evaluated"
                        if task_slot_admitted
                        else ",".join(
                            current_reuse_verdict["missing_policy_requirements"]
                        )
                    )
                )
                result["direct_slot_admitted_span_count"] = len(
                    current_reuse_verdict["distinct_span_ids"]
                )
                result["coverage_bundle_id"] = current_reuse_verdict[
                    "coverage_bundle_id"
                ]
                result["coverage_bundle_kind"] = current_reuse_verdict[
                    "coverage_bundle_kind"
                ]
                result["comparison_signature"] = current_reuse_verdict[
                    "comparison_signature"
                ]
                for field in (
                    "comparison_coverage_bundle_ids",
                    "comparison_target_pair_ids",
                    "comparison_direct_pair_ids",
                    "comparison_missing_direct_pair_ids",
                ):
                    result[field] = list(current_reuse_verdict.get(field) or [])
                result["direct_pair_coverage_complete"] = bool(
                    current_reuse_verdict.get("direct_pair_coverage_complete")
                )
                direct_pair_ready = bool(
                    comparison_contract
                    and result["direct_pair_coverage_complete"]
                )
                expected_arm_ids = {
                    str((comparison_contract.get("primary_arm") or {}).get("arm_id") or "")
                } | {
                    str(item.get("arm_id") or "")
                    for item in comparison_contract.get("comparator_arms") or []
                    if isinstance(item, dict)
                }
                observed_arm_ids = {
                    str(match.get("arm_id") or "")
                    for item in current_slot_supports
                    if isinstance(item, dict)
                    for match in ((item.get("comparison_evidence_v4") or {}).get("arm_matches") or [])
                    if isinstance(match, dict) and str(match.get("arm_id") or "")
                }
                comparison_arm_coverage_ready = bool(
                    comparison_contract
                    and expected_arm_ids - {""}
                    and expected_arm_ids - {""} <= observed_arm_ids
                )
                comparison_phase = (
                    result.get("comparison_retrieval_phase_v4")
                    if isinstance(result.get("comparison_retrieval_phase_v4"), dict)
                    else {}
                )
                comparison_phase_name = str(comparison_phase.get("phase") or "")
                arm_first_execution_complete = bool(
                    comparison_phase.get("arm_first_provider_execution_complete")
                )
                comparability_followup_complete = bool(
                    comparison_phase.get("comparability_followup_provider_execution_complete")
                )
                comparison_phase_complete = (
                    arm_first_execution_complete
                    if comparison_phase_name == "ARM_FIRST_PHASE"
                    else comparability_followup_complete
                    if comparison_phase_name == "COMPARABILITY_FOLLOWUP_PHASE"
                    else False
                )
                if comparison_contract:
                    comparison_phase.update({
                        "schema_version": "comparison_retrieval_phase_v4",
                        "comparison_arm_coverage_ready": comparison_arm_coverage_ready,
                        "direct_pair_coverage_complete": direct_pair_ready,
                        "comparison_synthesis_ready": False,
                        "admission_evaluated": True,
                        "next_phase": (
                            "COMPARABILITY_FOLLOWUP_PHASE"
                            if (
                                comparison_phase_name == "ARM_FIRST_PHASE"
                                and arm_first_execution_complete
                                and comparison_arm_coverage_ready
                            )
                            else "GAP_RESOLUTION_ELIGIBLE"
                            if (
                                comparison_phase_name == "COMPARABILITY_FOLLOWUP_PHASE"
                                and comparability_followup_complete
                            )
                            else ""
                        ),
                    })
                    result["comparison_retrieval_phase_v4"] = comparison_phase
                result["assertion_admission_status"] = (
                    "SLOT_ASSERTION_ADMITTED"
                    if current_slot_supports else "NO_SLOT_ASSERTION_ADMITTED"
                )
                result["scientific_obligation_status"] = (
                    "DIRECT_PAIR_READY"
                    if comparison_contract and direct_pair_ready
                    else "COMPARABILITY_PENDING"
                    if (
                        comparison_contract
                        and comparison_arm_coverage_ready
                    )
                    else "ARM_EVIDENCE_READY"
                    if (
                        comparison_contract
                        and bool(observed_arm_ids)
                    )
                    else "COMPARISON_RETRIEVAL_INCOMPLETE"
                    if comparison_contract else "SLOT_OBLIGATION_EVALUATED"
                )
                result["comparison_obligation_diagnostics"] = (
                    {
                        "comparison_contract_id": str(
                            comparison_contract.get("comparison_contract_id") or ""
                        ),
                        "execution_phase": comparison_phase_name,
                        "next_phase": str(comparison_phase.get("next_phase") or ""),
                        "provider_execution_complete": comparison_phase_complete,
                        "missing_requirements": list(
                            current_reuse_verdict.get("missing_policy_requirements") or []
                        ),
                        "target_pair_ids": list(
                            result.get("comparison_target_pair_ids") or []
                        ),
                        "direct_pair_ids": list(
                            result.get("comparison_direct_pair_ids") or []
                        ),
                        "missing_direct_pair_ids": list(
                            result.get("comparison_missing_direct_pair_ids") or []
                        ),
                        "candidate_diagnostics": list(
                            result.get("comparison_candidate_diagnostics") or []
                        ),
                        "diagnostic_reason_codes": sorted({
                            str(reason_code)
                            for candidate_diagnostic in result.get(
                                "comparison_candidate_diagnostics"
                            ) or []
                            if isinstance(candidate_diagnostic, dict)
                            for reason_code in candidate_diagnostic.get(
                                "reason_codes", []
                            )
                            if str(reason_code)
                        }),
                    }
                    if comparison_contract else {}
                )
                result["reused_direct_slot_admitted_assertion_count"] = len({
                    str(item.get("assertion_id") or "")
                    for item in current_slot_supports
                    if isinstance(item, dict) and str(item.get("source_id") or "") in set(result["reused_source_ids"])
                })
                result["reused_direct_slot_admitted_source_count"] = len({
                    str(item.get("source_id") or "")
                    for item in current_slot_supports
                    if isinstance(item, dict) and str(item.get("source_id") or "") in set(result["reused_source_ids"])
                })
                result["new_direct_slot_admitted_source_count"] = len({
                    str(item.get("source_id") or "")
                    for item in current_slot_supports
                    if isinstance(item, dict)
                    and str(item.get("source_id") or "")
                    and str(item.get("source_id") or "") not in set(result["reused_source_ids"])
                })
                provider_outcome = str(
                    (result.get("query_variant_execution_v3") or {}).get("terminal_outcome")
                    or ""
                )
                targeted_admission = (
                    search_payload.get("targeted_admission")
                    if isinstance(search_payload.get("targeted_admission"), dict)
                    else {}
                )
                candidate_pool_diagnostics = (
                    search_payload.get("candidate_pool_diagnostics")
                    if isinstance(search_payload.get("candidate_pool_diagnostics"), dict)
                    else {}
                )
                result["candidate_pool_diagnostics"] = dict(candidate_pool_diagnostics)
                shared_pool_available_count = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get(
                            "shared_raw_candidate_pool_available_count"
                        ) or 0
                    ),
                )
                shared_pool_selected_count = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get(
                            "shared_raw_candidate_pool_selected_count"
                        ) or 0
                    ),
                )
                raw_candidates_rejected_before_import = bool(
                    int(result.get("raw_provider_result_count") or 0) > 0
                    and not candidates
                )
                coarse_prefilter_evaluated = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get("coarse_prefilter_evaluated")
                        or targeted_admission.get("coarse_prefilter_evaluated")
                        or 0
                    ),
                )
                coarse_prefilter_accepted = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get("coarse_prefilter_accepted")
                        or targeted_admission.get("coarse_prefilter_accepted")
                        or 0
                    ),
                )
                strict_alignment_evaluated = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get("strict_alignment_evaluated")
                        or targeted_admission.get("evaluated")
                        or 0
                    ),
                )
                strict_alignment_accepted = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get("strict_alignment_accepted")
                        or targeted_admission.get("accepted")
                        or 0
                    ),
                )
                previously_seen_rejected = max(
                    0,
                    int(
                        candidate_pool_diagnostics.get("removed_as_previously_seen")
                        or search_payload.get("removed_as_previously_seen")
                        or 0
                    ),
                )
                selection_truncated = bool(
                    int(search_payload.get("new_candidate_count") or 0) > 0
                    and not candidates
                )
                alignment_rejected = bool(
                    raw_candidates_rejected_before_import
                    and coarse_prefilter_evaluated > 0
                    and coarse_prefilter_accepted == 0
                )
                admission_rejected = bool(
                    raw_candidates_rejected_before_import
                    and not alignment_rejected
                    and strict_alignment_evaluated > 0
                    and strict_alignment_accepted == 0
                )
                candidate_disposition = (
                    "SHARED_DISCOVERY_CANDIDATES_RETAINED"
                    if shared_pool_selected_count > 0 and candidates
                    else "SHARED_DISCOVERY_SELECTION_OR_ADMISSION_SHORTAGE"
                    if shared_pool_available_count > 0
                    and int(result.get("raw_provider_result_count") or 0) == 0
                    else "RAW_PROVIDER_ZERO"
                    if int(result.get("raw_provider_result_count") or 0) == 0
                    else "COARSE_ALIGNMENT_REJECTED"
                    if alignment_rejected
                    else "STRICT_ADMISSION_REJECTED"
                    if admission_rejected
                    else "PREVIOUSLY_SEEN_DEDUPLICATED"
                    if raw_candidates_rejected_before_import and previously_seen_rejected > 0
                    else "SELECTION_OR_IMPORT_NOT_RETAINED"
                    if raw_candidates_rejected_before_import or selection_truncated
                    else "CANDIDATES_RETAINED"
                )
                result["candidate_disposition"] = candidate_disposition
                result["candidate_disposition_counts"] = {
                    "coarse_prefilter_evaluated": coarse_prefilter_evaluated,
                    "coarse_prefilter_accepted": coarse_prefilter_accepted,
                    "strict_alignment_evaluated": strict_alignment_evaluated,
                    "strict_alignment_accepted": strict_alignment_accepted,
                    "previously_seen_rejected": previously_seen_rejected,
                    "shared_raw_candidate_pool_available": shared_pool_available_count,
                    "shared_raw_candidate_pool_selected": shared_pool_selected_count,
                }
                if provider_outcome in {
                    "QUERY_PLAN_CONTRACT_ERROR",
                    "QUERY_COMPILATION_REPAIR_REQUIRED",
                    "INVALID_QUERY",
                }:
                    result["provider_dispatch_status"] = (
                        "NOT_SUBMITTED_QUERY_PLAN_CONTRACT"
                        if provider_outcome == "QUERY_PLAN_CONTRACT_ERROR"
                        else "NOT_SUBMITTED_LOCAL_QUERY_COMPILATION"
                    )
                    result["provider_dispatch_reason"] = provider_outcome.lower()
                    result["failure_stage"] = (
                        "query_plan_contract"
                        if provider_outcome == "QUERY_PLAN_CONTRACT_ERROR"
                        else "provider_query_compilation"
                    )
                result["status"] = (
                    "DIRECT_SLOT_ADMITTED"
                    if task_slot_admitted
                    else "COMPARABILITY_AUDIT_PENDING"
                    if (
                        comparison_contract
                        and comparison_arm_coverage_ready
                    )
                    else "ARM_EVIDENCE_COLLECTED"
                    if (
                        comparison_contract
                        and bool(observed_arm_ids)
                    )
                    else "ALIGNMENT_INTEGRITY_ERROR"
                    if result["alignment_integrity_error_count"] > 0
                    else "ALIGNMENT_NOT_EXECUTED"
                    if result["source_ids"]
                    and result["alignment_completed_count"] == 0
                    and result["alignment_not_executed_count"] > 0
                    else "CANDIDATES_IMPORTED_AWAITING_ADMISSION"
                    if result["source_ids"]
                    else "PROVIDER_DEFERRED"
                    if provider_outcome == "PROVIDER_DEFERRED"
                    else "QUERY_PLAN_CONTRACT_ERROR"
                    if provider_outcome == "QUERY_PLAN_CONTRACT_ERROR"
                    else "QUERY_COMPILATION_REPAIR_REQUIRED"
                    if provider_outcome == "QUERY_COMPILATION_REPAIR_REQUIRED"
                    else "SEARCH_ERROR"
                    if provider_outcome == "SEARCH_ERROR"
                    else "INVALID_QUERY"
                    if provider_outcome == "INVALID_QUERY"
                    else "ALIGNMENT_SHORTAGE"
                    if alignment_rejected
                    else "ADMISSION_SHORTAGE"
                    if admission_rejected
                    else "CANDIDATE_DEDUPLICATED"
                    if raw_candidates_rejected_before_import and previously_seen_rejected > 0
                    else "CANDIDATE_SELECTION_SHORTAGE"
                    if raw_candidates_rejected_before_import or selection_truncated
                    else "COVERAGE_SHORTAGE"
                )
                diagnostic["coverage_status"] = (
                    "DIRECT_SLOT_ADMITTED"
                    if task_slot_admitted
                    else "COMPARABILITY_AUDIT_PENDING"
                    if (
                        comparison_contract
                        and comparison_arm_coverage_ready
                    )
                    else "ARM_EVIDENCE_COLLECTED"
                    if (
                        comparison_contract
                        and bool(observed_arm_ids)
                    )
                    else "ALIGNMENT_INTEGRITY_ERROR"
                    if result["alignment_integrity_error_count"] > 0
                    else "ALIGNMENT_NOT_EXECUTED"
                    if result["source_ids"]
                    and result["alignment_completed_count"] == 0
                    and result["alignment_not_executed_count"] > 0
                    else "CANDIDATES_IMPORTED_AWAITING_ADMISSION"
                    if result["source_ids"]
                    else "PROVIDER_DEFERRED"
                    if provider_outcome == "PROVIDER_DEFERRED"
                    else "QUERY_PLAN_CONTRACT_ERROR"
                    if provider_outcome == "QUERY_PLAN_CONTRACT_ERROR"
                    else "QUERY_COMPILATION_REPAIR_REQUIRED"
                    if provider_outcome == "QUERY_COMPILATION_REPAIR_REQUIRED"
                    else "SEARCH_ERROR"
                    if provider_outcome == "SEARCH_ERROR"
                    else "INVALID_QUERY"
                    if provider_outcome == "INVALID_QUERY"
                    else "ALIGNMENT_SHORTAGE"
                    if alignment_rejected
                    else "ADMISSION_SHORTAGE"
                    if admission_rejected
                    else "CANDIDATE_DEDUPLICATED"
                    if raw_candidates_rejected_before_import and previously_seen_rejected > 0
                    else "CANDIDATE_SELECTION_SHORTAGE"
                    if raw_candidates_rejected_before_import or selection_truncated
                    else "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY"
                )
            except Exception as exc:
                exception_type = type(exc).__name__
                exception_message = str(exc)[:180]
                result.update({
                    "status": "RETRIEVAL_EXECUTION_ERROR",
                    "provider_dispatch_status": "INTERNAL_RETRIEVAL_EXECUTION_ERROR",
                    "provider_dispatch_reason": f"internal_failure_stage:{failure_stage}",
                    "failure_stage": failure_stage,
                    "exception_type": exception_type,
                    "exception_message": exception_message,
                })
                diagnostic.update({
                    "status": "retrieval_execution_error",
                    "failure_stage": failure_stage,
                    "exception_type": exception_type,
                    "exception_message": exception_message,
                    "error": f"{exception_type}: {exception_message}",
                    "coverage_status": "RETRIEVAL_EXECUTION_ERROR",
                })
        context["task_results"].append(result)
        context["task_diagnostics"].append(diagnostic)
        execution_order[-1].update(
            {
                "status": str(result.get("status") or "").upper(),
                "checkpoint_reusable": v3_retrieval_task_checkpoint_reusable(
                    {"task_id": task_id, "status": result.get("status")}
                ),
            }
        )
        if (
            str(task.get("query_mode") or "").upper() == "FOUNDATIONAL_CONTEXT"
            and isinstance(shared_context, dict)
            and shared_context.get("owner_sub_hypothesis_id") == sub_id
        ):
            for source_id in result.get("source_ids") or []:
                if source_id and source_id not in shared_context["source_ids"]:
                    shared_context["source_ids"].append(source_id)
            for assertion_id in result.get("assertion_ids") or []:
                if assertion_id and assertion_id not in shared_context["assertion_ids"]:
                    shared_context["assertion_ids"].append(assertion_id)
            shared_context["task_id"] = task_id
        if semantic_execution_key:
            context["query_results_by_fingerprint"][semantic_execution_key] = result
            context["task_specs_by_fingerprint"][semantic_execution_key] = dict(spec)
        execution_summary = retrieval_run_context["execution_summary_by_sh"].setdefault(
            sub_id,
            {
                "executed_task_count": 0,
                "new_source_count": 0,
                "reused_source_count": 0,
                "admitted_assertion_count": 0,
            },
        )
        execution_summary["executed_task_count"] += 1
        execution_summary["new_source_count"] += len(result.get("new_source_ids") or [])
        execution_summary["reused_source_count"] += len(result.get("reused_source_ids") or [])
        execution_summary["admitted_assertion_count"] += len(result.get("assertion_ids") or [])
        log_event(
            "SCIENCE",
            "v3_retrieval_task_complete",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            task_id=task_id,
            wave_index=wave,
            slot=diagnostic["slot"],
            query_branch=query_branch,
            query_mode=str(task.get("query_mode") or ""),
            query_fingerprint=fingerprint,
            new_candidate_budget=int(profile.get("candidate_budget") or 0),
            excluded_candidate_key_count=int(result.get("excluded_candidate_key_count") or 0),
            reused_assertion_count=len(result.get("assertion_ids") or []) if result.get("reused_source_ids") else 0,
            status=str(result.get("status") or ""),
            source_count=len(result.get("source_ids") or []),
            new_source_count=len(result.get("new_source_ids") or []),
            new_import_count=len(result.get("new_source_ids") or []),
            reused_source_count=len(result.get("reused_source_ids") or []),
            candidate_count=int(result.get("candidate_count") or 0),
            metadata_kept_count=int(result.get("metadata_kept_count") or 0),
            fulltext_available_count=int(result.get("fulltext_available_count") or 0),
            alignment_completed_count=int(result.get("alignment_completed_count") or 0),
            alignment_not_executed_count=int(result.get("alignment_not_executed_count") or 0),
            alignment_integrity_error_count=int(result.get("alignment_integrity_error_count") or 0),
            target_slot_terminal_positive_count=int(
                result.get("target_slot_terminal_positive_count") or 0
            ),
            target_slot_pending_pair_count=int(
                result.get("target_slot_pending_pair_count") or 0
            ),
            direct_slot_admitted_count=int(result.get("direct_slot_admitted_count") or 0),
            new_direct_slot_admitted_source_count=int(result.get("new_direct_slot_admitted_source_count") or 0),
            reused_direct_slot_admitted_source_count=int(result.get("reused_direct_slot_admitted_source_count") or 0),
            reused_direct_slot_admitted_assertion_count=int(result.get("reused_direct_slot_admitted_assertion_count") or 0),
            direct_slot_admitted_span_count=int(result.get("direct_slot_admitted_span_count") or 0),
            distinct_paper_count_for_slot=len(
                (result.get("direct_slot_admitted_source_ids_by_slot") or {}).get(
                    diagnostic["slot"], []
                )
            ),
            coverage_bundle_id=str(result.get("coverage_bundle_id") or ""),
            coverage_bundle_kind=str(result.get("coverage_bundle_kind") or ""),
            comparison_signature=str(result.get("comparison_signature") or ""),
            comparison_execution_phase=str(
                (result.get("comparison_retrieval_phase_v4") or {}).get("phase")
                if isinstance(result.get("comparison_retrieval_phase_v4"), dict)
                else ""
            ),
            scientific_obligation_status=str(
                result.get("scientific_obligation_status") or ""
            ),
            comparison_candidate_diagnostic_count=len(
                result.get("comparison_candidate_diagnostics") or []
            ),
            comparison_diagnostic_reason_codes=sorted({
                str(reason_code)
                for candidate_diagnostic in result.get(
                    "comparison_candidate_diagnostics"
                ) or []
                if isinstance(candidate_diagnostic, dict)
                for reason_code in candidate_diagnostic.get("reason_codes", [])
                if str(reason_code)
            }),
            slot_policy_verdict=str(result.get("slot_policy_verdict") or ""),
            provider_dispatch_status=str(result.get("provider_dispatch_status") or ""),
            provider_dispatch_reason=str(result.get("provider_dispatch_reason") or ""),
            failure_stage=str(result.get("failure_stage") or ""),
            exception_type=str(result.get("exception_type") or ""),
            exception_message=str(result.get("exception_message") or ""),
            independent_confirmation_required=bool(
                result.get("independent_confirmation_required")
            ),
            raw_provider_result_count=int(result.get("raw_provider_result_count") or 0),
            configured_providers=list(result.get("configured_providers") or []),
            dispatched_providers=list(result.get("dispatched_providers") or []),
            skipped_providers=list(result.get("skipped_providers") or []),
            deferred_provider_count=int(result.get("deferred_provider_count") or 0),
            foundation_context_count=int(result.get("foundation_context_count") or 0),
            background_only_count=int(result.get("background_only_count") or 0),
            contract_rejected_count=int(result.get("contract_rejected_count") or 0),
            candidate_preparation=dict(result.get("candidate_preparation") or {}),
            candidate_commit=dict(result.get("candidate_commit") or {}),
        )

    if active_wave is not None:
        log_event(
            "SCIENCE",
            "v3_retrieval_wave_completed",
            project_id=project_id,
            wave_index=active_wave,
        )

    for context in active_contexts:
        sub_id = context["sub_hypothesis_id"]
        execution_payload = decode_payload(execute_research_question_retrieval_plan(
            project_id, sub_id, context["task_results"]
        ))
        paper_reviews = sh_paper_reviews(context)
        sh_synthesis = synthesize_sh_evidence(
            context["contract"], paper_reviews
        )
        profile_totals = _v3_slot_profile_totals(context["tasks"])
        sh_discovery_state = context.get("sh_discovery_state")
        sh_discovery_summary = (
            dict(sh_discovery_state)
            if isinstance(sh_discovery_state, dict)
            else {}
        )
        sh_discovery_summary.pop("candidate_pool", None)
        required_slots = [
            str(task.get("slot") or task.get("requirement") or "")
            for task in context["tasks"]
            if str(task.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
            and str(task.get("slot") or task.get("requirement") or "")
        ]
        synthesis_coverage = (
            sh_synthesis.get("coverage")
            if isinstance(sh_synthesis.get("coverage"), dict)
            else {}
        )
        sh_discovery_summary["unresolved_obligations"] = unresolved_sh_obligations(
            synthesis_coverage
            or (
                execution_payload.get("slot_coverage_ledger")
                if isinstance(execution_payload.get("slot_coverage_ledger"), dict)
                else {}
            ),
            required_slots=required_slots,
        )
        additional_searches = [
            build_targeted_gap_query(
                obligation,
                context["contract"],
                sub_hypothesis_id=sub_id,
            )
            for obligation in sh_discovery_summary["unresolved_obligations"]
        ]
        targeted_gap_tasks = [
            dict(task)
            for task in context.get("tasks", [])
            if isinstance(task, dict) and task.get("targeted_gap_retrieval") is True
        ]
        if targeted_gap_tasks:
            additional_searches = [
                {
                    **dict(item),
                    "status": "EXHAUSTED_AFTER_ONE_TARGETED_WAVE",
                }
                for item in additional_searches
                if isinstance(item, dict)
            ]
        completed_targeted_task_ids = {
            str(row.get("task_id") or "")
            for row in context.get("task_results", [])
            if isinstance(row, dict)
            and any(
                str(row.get("task_id") or "") == str(task.get("task_id") or "")
                for task in targeted_gap_tasks
            )
        }
        context["sh_run"].update({
            "status": "COMPLETED",
            "paper_reviews": paper_reviews,
            "synthesis": sh_synthesis,
            "coverage": synthesis_coverage,
            "unresolved_obligations": list(
                sh_discovery_summary["unresolved_obligations"]
            ),
            "additional_searches": additional_searches,
            "additional_search_execution": {
                "wave_limit": MAX_ADDITIONAL_WAVES,
                "scheduled_task_count": len(targeted_gap_tasks),
                "completed_task_count": len(completed_targeted_task_ids),
                "status": (
                    "EXECUTED"
                    if targeted_gap_tasks
                    else "NOT_REQUIRED"
                ),
            },
            "coverage_gap_status": (
                "UNRESOLVED_AFTER_TARGETED_WAVE"
                if sh_discovery_summary["unresolved_obligations"]
                and targeted_gap_tasks
                else "UNRESOLVED_BEFORE_TARGETED_WAVE"
                if sh_discovery_summary["unresolved_obligations"]
                else "SATISFIED"
            ),
            "token_budget": {
                "query_generation": {
                    "branch_count": int(context["sh_query_plan"].get("branch_count") or 0),
                    "additional_gap_query_count": len(additional_searches),
                },
                "retrieval": {
                    "selected_paper_count": len(
                        (context.get("sh_discovery_state") or {}).get("candidate_pool") or []
                    ),
                    "targeted_gap_task_count": len(targeted_gap_tasks),
                },
                "paper_review": {
                    "paper_count": len(paper_reviews),
                    "proposition_count": sum(
                        len(item.get("document_proposition_artifact", {}).get("propositions") or [])
                        for item in paper_reviews
                        if isinstance(item, dict)
                        and isinstance(item.get("document_proposition_artifact"), dict)
                    ),
                },
                "sh_synthesis": {"invocation_count": 1},
                "paper_review_count": len(paper_reviews),
                "reviewed_assertion_count": sum(
                    len(item.get("assertions") or [])
                    for item in paper_reviews
                    if isinstance(item, dict)
                ),
                "additional_wave_limit": MAX_ADDITIONAL_WAVES,
            },
        })
        try:
            context["sh_run"] = persist_sh_retrieval_run(context["sh_run"])
        except (OSError, TypeError, ValueError) as exc:
            context["sh_run"]["artifact_persistence_error"] = (
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
        log_event(
            "SCIENCE",
            "v3_slot_retrieval_profile_applied",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            imported_source_count=len(context["imported_source_ids_set"]),
            source_admission_policy="unchanged_source_span_explicit_assertion_and_typed_slot_gates",
            **profile_totals,
        )
        branch_reports_by_id[sub_id] = {
            "sub_hypothesis_id": sub_id,
            "status": str(execution_payload.get("retrieval_execution", execution_payload).get("status") or execution_payload.get("status") or ""),
            "contract_coherence_audit": coherence_audits[sub_id],
            "task_count": len(context["tasks"]),
            "search_count": context["search_count"],
            "imported_source_ids": list(context["imported_source_ids"]),
            "task_diagnostics": context["task_diagnostics"],
            "candidate_redundancy_totals": profile_totals,
            "execution": execution_payload,
            "retrieval_execution_status": str(execution_payload.get("retrieval_execution_status") or "COMPLETE"),
            "candidate_intake_status": str(execution_payload.get("candidate_intake_status") or "EMPTY"),
            "alignment_status": str(execution_payload.get("alignment_status") or "NOT_EXECUTED"),
            "candidate_count": int(execution_payload.get("candidate_count") or 0),
            "metadata_kept_count": int(execution_payload.get("metadata_kept_count") or 0),
            "fulltext_available_count": int(execution_payload.get("fulltext_available_count") or 0),
            "alignment_completed_count": int(execution_payload.get("alignment_completed_count") or 0),
            "alignment_not_executed_count": int(execution_payload.get("alignment_not_executed_count") or 0),
            "alignment_integrity_error_count": int(execution_payload.get("alignment_integrity_error_count") or 0),
            "target_slot_terminal_positive_count": int(
                execution_payload.get("target_slot_terminal_positive_count") or 0
            ),
            "target_slot_pending_pair_count": int(
                execution_payload.get("target_slot_pending_pair_count") or 0
            ),
            "admission_status": str(execution_payload.get("admission_status") or "EMPTY"),
            "evidence_coverage_status": str(execution_payload.get("evidence_coverage_status") or "EMPTY"),
            "aggregate_evidence_ready": bool(execution_payload.get("aggregate_evidence_ready")),
            "required_direct_slot_ids": list(execution_payload.get("required_direct_slot_ids") or []),
            "covered_direct_slot_ids": list(execution_payload.get("covered_direct_slot_ids") or []),
            "missing_direct_slot_ids": list(execution_payload.get("missing_direct_slot_ids") or []),
            "direct_evidence_paper_count": int(execution_payload.get("direct_evidence_paper_count") or 0),
            "slot_coverage_ledger": dict(execution_payload.get("slot_coverage_ledger") or {}),
            "sh_discovery": sh_discovery_summary,
            "sh_retrieval_run": dict(context.get("sh_run") or {}),
        }
        log_event(
            "SCIENCE",
            "v3_subhypothesis_evidence_coverage",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            retrieval_execution_status=str(execution_payload.get("retrieval_execution_status") or ""),
            evidence_coverage_status=str(execution_payload.get("evidence_coverage_status") or "EMPTY"),
            aggregate_evidence_ready=bool(execution_payload.get("aggregate_evidence_ready")),
            required_direct_slot_ids=list(execution_payload.get("required_direct_slot_ids") or []),
            covered_direct_slot_ids=list(execution_payload.get("covered_direct_slot_ids") or []),
            missing_direct_slot_ids=list(execution_payload.get("missing_direct_slot_ids") or []),
            direct_evidence_paper_count=int(execution_payload.get("direct_evidence_paper_count") or 0),
            slot_policy_verdicts={
                slot: str(item.get("policy_verdict") or "")
                for slot, item in (execution_payload.get("slot_coverage_ledger") or {}).items()
                if isinstance(item, dict)
            },
            provider_dispatch_statuses={
                slot: str(item.get("provider_dispatch_status") or "")
                for slot, item in (execution_payload.get("slot_coverage_ledger") or {}).items()
                if isinstance(item, dict)
            },
            candidate_count=int(execution_payload.get("candidate_count") or 0),
            metadata_kept_count=int(execution_payload.get("metadata_kept_count") or 0),
            fulltext_available_count=int(execution_payload.get("fulltext_available_count") or 0),
            alignment_completed_count=int(execution_payload.get("alignment_completed_count") or 0),
            alignment_not_executed_count=int(execution_payload.get("alignment_not_executed_count") or 0),
            alignment_integrity_error_count=int(execution_payload.get("alignment_integrity_error_count") or 0),
        )

    # Persist only the compact scheduling audit. Every SH execution has already
    # been committed as a detached ledger, so this must not materialize papers
    # or full text merely to append orchestration metadata.
    try:
        science_state_manager().commit_v3_project_patch(
            project_id,
            field_updates={
                "subhypothesis_retrieval_execution_order": {
            "schema_version": "v3_retrieval_round_robin_schedule_v1",
            "plan_schema_version": RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            "entries": execution_order,
            "reused_completed_task_rows": reused_completed_task_rows,
            "superseded_plan_audits": superseded_plan_audits,
            "updatedAt": time.time(),
                },
                "v3_retrieval_run_context": retrieval_run_context,
                "research_contract_coherence_audits_v3": coherence_audits,
            },
            artifact_groups=("workflow",),
            operation="PERSIST_V3_RETRIEVAL_SCHEDULING_AUDIT",
        )
    except Exception as exc:
        log_event("WARN", "v3_retrieval_execution_order_persist_failed", project_id=project_id, error=f"{type(exc).__name__}: {str(exc)[:180]}")

    ordered_ids = [context["sub_hypothesis_id"] for context in active_contexts]
    branch_reports = [
        branch_reports_by_id[sub_id]
        for sub_id in [
            *domain_blocked_ids,
            *coherence_blocked_ids,
            *coherence_deferred_ids,
            *ordered_ids,
            *reused_completed_ids,
        ]
        if sub_id in branch_reports_by_id
    ]
    return {
        "schema_version": "zhizhi_research_question_retrieval_execution_v3",
        "status": (
            "domain_contract_repair_required"
            if domain_blocked_ids
            else "research_contract_coherence_blocked"
            if coherence_blocked_ids
            else "research_question_slot_retrieval_executed"
        ),
        "branches": branch_reports,
        "executed_sub_hypothesis_ids": ordered_ids,
        "coherence_blocked_sub_hypothesis_ids": coherence_blocked_ids,
        "domain_blocked_sub_hypothesis_ids": domain_blocked_ids,
        "coherence_deferred_sub_hypothesis_ids": coherence_deferred_ids,
        "coherence_recovery_kind": coherence_recovery_kind,
        "reused_sub_hypothesis_ids": reused_completed_ids,
        "execution_order": execution_order,
        "superseded_plan_audits": superseded_plan_audits,
        "no_result_rule": "Empty retrieval results are coverage diagnostics only and cannot establish a scientific gap.",
        "candidate_redundancy_policy": "V3 slot profiles expand metadata/full-text attempts only; they do not relax source-bound evidence admission.",
        "legacy_causal_workflow_used": False,
    }


def run_autogen_research_flow(
    project_id: str,
    goal: str = "",
    groupchat_id: str = "",
    restart_from_decomposition: bool = False,
) -> str:
    try:
        from .science_core import (
            decompose_research_objective,
            default_literature_providers,
            audit_and_persist_research_proposal,
            build_and_persist_proposal_brief,
            execute_research_question_retrieval_plan,
            import_literature_search_result,
            load_project,
            reassess_v3_imported_candidates_for_contract,
            rebind_project_research_domain_contracts_v3,
            run_socrates_type_specific_review,
            search_papers_stratified,
            write_and_persist_research_proposal,
            run_tanxi_gap_exploration,
            restart_project_from_subhypothesis_decomposition,
            activate_normalized_science_project_storage,
        )
    except ImportError:
        from science_core import (
            decompose_research_objective,
            default_literature_providers,
            audit_and_persist_research_proposal,
            build_and_persist_proposal_brief,
            execute_research_question_retrieval_plan,
            import_literature_search_result,
            load_project,
            reassess_v3_imported_candidates_for_contract,
            rebind_project_research_domain_contracts_v3,
            run_socrates_type_specific_review,
            search_papers_stratified,
            write_and_persist_research_proposal,
            run_tanxi_gap_exploration,
            restart_project_from_subhypothesis_decomposition,
            activate_normalized_science_project_storage,
        )

    try:
        from ._gap_semantic_audit import GapSemanticAuditInvocationError
    except ImportError:
        from _gap_semantic_audit import GapSemanticAuditInvocationError

    if restart_from_decomposition:
        restart_project_from_subhypothesis_decomposition(
            project_id,
            reason="autogen_groupchat_fresh_subhypothesis_decomposition",
        )
    project = load_project(project_id)
    try:
        from ._autogen_run_config import resolve_effective_autogen_run_config
        from ._project import project_research_domain_context, save_project
        from ._science_execution_policy import (
            persist_effective_science_execution_policy,
            resolve_science_execution_policy,
        )
    except ImportError:
        from _autogen_run_config import resolve_effective_autogen_run_config
        from _project import project_research_domain_context, save_project
        from _science_execution_policy import (
            persist_effective_science_execution_policy,
            resolve_science_execution_policy,
        )
    execution_policy = resolve_science_execution_policy(project)
    canonical_providers = default_literature_providers(
        domain=project_research_domain_context(project),
        query=goal or str(project.get("objective") or ""),
    )
    effective_run_config = resolve_effective_autogen_run_config(
        providers=canonical_providers,
        use_llm=execution_policy.use_llm,
        restart_from_decomposition=restart_from_decomposition,
    )
    requested_run_config = {
        "project_id": project_id,
        "goal": goal,
        "groupchat_id": groupchat_id,
        "restart_from_decomposition": bool(restart_from_decomposition),
    }
    effective_run_config_payload = effective_run_config.to_dict()
    providers = list(effective_run_config.providers)
    use_llm = effective_run_config.use_llm
    max_subhypotheses = effective_run_config.max_subhypotheses
    max_round = effective_run_config.max_round
    speaker_selection_method = effective_run_config.speaker_selection_method
    human_input_mode = effective_run_config.human_input_mode
    use_native_autogen = effective_run_config.use_native_autogen
    persist_effective_science_execution_policy(project, execution_policy)
    project["requested_autogen_run_config"] = requested_run_config
    project["effective_autogen_run_config"] = effective_run_config_payload
    log_event(
        "AUTOGEN",
        "effective_autogen_run_config_resolved",
        project_id=project_id,
        requested_config=requested_run_config,
        effective_config=effective_run_config_payload,
    )
    # V3 owns the entire research lifecycle. Persist this mode before any
    # tool boundary is reached so direct task/DAG calls can be rejected even
    # when they bypass the model-facing schema.
    if project.get("workflow_mode") != "V3_GROUPCHAT_ONLY":
        project["workflow_mode"] = "V3_GROUPCHAT_ONLY"
        project["updatedAt"] = time.time()
        save_project(project)
    v3_cutover_audit = research_question_project_cutover_audit(project)
    requires_v3_redecomposition = bool(
        restart_from_decomposition
        or not project.get("sub_hypotheses")
        or not v3_cutover_audit.get("all_subhypotheses_v3")
    )
    if requires_v3_redecomposition:
        if project.get("sub_hypotheses") and not restart_from_decomposition:
            restart_project_from_subhypothesis_decomposition(
                project_id,
                reason="autogen_groupchat_v3_contract_cutover",
            )
        decomposition = json.loads(
            decompose_research_objective(
                project_id,
                max_subhypotheses=max_subhypotheses,
                use_llm=use_llm,
            )
        )
        project = load_project(project_id)
    else:
        decomposition = project.get("objective_decomposition", {})
    try:
        from ._project import save_project
        from ._subhypothesis_annotation import annotate_project_subhypotheses
    except ImportError:
        from _project import save_project
        from _subhypothesis_annotation import annotate_project_subhypotheses
    # Every GroupChat run starts from a single V3 question-contract set. A
    # legacy or mixed SH collection is discarded and re-decomposed above; it
    # is never translated into an input/mediator/outcome retrieval contract.
    # The decomposition count remains exactly the validated V3 output, rather
    # than being topped up with heuristic candidates.
    persist_effective_science_execution_policy(project, execution_policy)
    domain_binding_audit = rebind_project_research_domain_contracts_v3(project)
    project["subhypothesis_annotation_summary"] = annotate_project_subhypotheses(project)
    v3_cutover_audit = research_question_project_cutover_audit(project)
    v3_contract_preflight = research_question_contract_declaration_summary_v3(project)
    project["research_question_cutover_audit"] = v3_cutover_audit
    project["research_question_contract_preflight"] = v3_contract_preflight
    project["updatedAt"] = time.time()
    save_project(project)
    log_event(
        "SCIENCE",
        "v3_research_domain_contract_binding_completed",
        project_id=project_id,
        status=str(domain_binding_audit.get("status") or ""),
        rebound_sub_hypothesis_ids=list(
            domain_binding_audit.get("rebound_sub_hypothesis_ids") or []
        ),
        project_domain_status=str(
            (domain_binding_audit.get("project_domain_contract") or {}).get(
                "status"
            )
            or ""
        ),
    )
    decomposition_summary = (
        project.get("objective_decomposition")
        if isinstance(project.get("objective_decomposition"), dict)
        else {}
    )
    protocol_block = decomposition_protocol_block_result_v3(
        project_id=project_id,
        decomposition=decomposition_summary,
        contract_preflight=v3_contract_preflight,
    )
    if protocol_block:
        log_event(
            "AUTOGEN",
            "groupchat_not_started_v3_decomposition_blocked",
            project_id=project_id,
            status=str(protocol_block.get("status") or ""),
            raw_llm_candidate_count=int(
                (decomposition_summary.get("candidate_pool_policy") or {}).get(
                    "raw_llm_candidate_count"
                )
                or 0
            ),
            repair_candidate_count=int(
                (decomposition_summary.get("candidate_pool_policy") or {}).get(
                    "raw_repair_candidate_count"
                )
                or 0
            ),
            validation_error_code_counts=dict(
                (decomposition_summary.get("candidate_validation_audit") or {}).get(
                    "validation_error_code_counts"
                )
                or {}
            ),
        )
        return json.dumps(protocol_block, ensure_ascii=False, indent=2)
    # The explicit state upgrade is a GroupChat preflight, never a lazy read
    # fallback.  Subsequent retrieval and TanXi paths resolve only immutable
    # contract refs and per-SH execution ledgers.
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    state_manager = science_state_manager()
    normalized_layout = state_manager.normalized_project_layout(project_id)
    if not bool(normalized_layout.get("manifest_exists")):
        activation_run_id = f"autogen_groupchat_v3_preflight_{int(time.time() * 1000)}"
        activation = activate_normalized_science_project_storage(
            project_id,
            run_id=activation_run_id,
        )
        activation_manifest = (
            activation.get("manifest")
            if isinstance(activation.get("manifest"), dict)
            else {}
        )
        log_event(
            "SCIENCE",
            "v3_normalized_project_storage_activated",
            project_id=project_id,
            run_id=activation_run_id,
            activation_status=str(activation.get("status") or ""),
            state_version=int(activation.get("state_version") or 0),
            contract_count=len(activation_manifest.get("subhypothesis_contract_refs") or {}),
        )
        project = load_project(project_id)
    manifest = state_manager.get_project_manifest(project_id)
    if not isinstance(manifest.get("subhypothesis_contract_refs"), dict) or not manifest.get("subhypothesis_contract_refs"):
        migration = state_manager.migrate_v3_research_question_state(project_id)
        log_event(
            "SCIENCE",
            "v3_research_question_state_migrated",
            project_id=project_id,
            state_version=int(migration.get("state_version") or 0),
            contract_count=int(migration.get("contract_count") or 0),
            execution_count=int(migration.get("execution_count") or 0),
        )
        project = load_project(project_id)
    log_event(
        "SCIENCE",
        "groupchat_v3_contract_preflight_applied",
        project_id=project_id,
        redecomposed=requires_v3_redecomposition,
        ready_subhypotheses=v3_contract_preflight.get("ready_sub_hypothesis_ids", []),
        pending_subhypotheses=v3_contract_preflight.get("pending_sub_hypothesis_ids", []),
    )
    decomposition = project.get("objective_decomposition", decomposition)
    resume_record: dict[str, Any] | None = None
    if not groupchat_id and not restart_from_decomposition:
        # A retry may only retain the project id. In that case, reattach the
        # newest interrupted GroupChat for that project instead of opening a
        # second execution history.
        resume_record = latest_groupchat_checkpoint(
            project_id=project_id,
            groupchat_id="",
        )
        if isinstance(resume_record, dict):
            groupchat_id = str(resume_record.get("groupchat_id") or "").strip()
    if groupchat_id:
        groupchat_spec = load_json(
            existing_autogen_path(
                autogen_groupchat_dir(),
                AUTOGEN_DIR,
                groupchat_id,
                additional_dirs=[LEGACY_AUTOGEN_DIR],
            )
        )
        ensure_groupchat_matches_project(groupchat_spec, project_id, groupchat_id)
        if resume_record is None and not restart_from_decomposition:
            resume_record = latest_groupchat_checkpoint(
                project_id=project_id,
                groupchat_id=groupchat_id,
            )
    else:
        groupchat_spec = json.loads(
            create_autogen_groupchat(
                project_id=project_id,
                goal=goal or str(project.get("objective", "")),
                max_round=max_round,
                speaker_selection_method=speaker_selection_method,
                human_input_mode=human_input_mode,
                use_native_autogen=use_native_autogen,
            )
        )
        groupchat_id = str(groupchat_spec.get("groupchat_id"))

    run_id = new_autogen_run_id()
    prior_checkpoint = (
        (resume_record.get("state") or {}).get("checkpoint")
        if isinstance(resume_record, dict)
        and isinstance(resume_record.get("state"), dict)
        and isinstance((resume_record.get("state") or {}).get("checkpoint"), dict)
        else {}
    )
    resume_from_stage = str(prior_checkpoint.get("resume_from_stage") or "").strip()
    prior_execution_order = (
        (resume_record.get("state") or {}).get(
            "subhypothesis_retrieval_execution_order"
        )
        if isinstance(resume_record, dict)
        and isinstance(resume_record.get("state"), dict)
        else {}
    )
    (
        prior_completed_retrieval_task_ids,
        prior_resumable_retrieval_task_ids,
    ) = v3_checkpoint_retrieval_task_ids(prior_execution_order)
    resume_retrieval_from_checkpoint = resume_from_stage in {
        "tanxi_gap_exploration",
        "type_directed_tanxi_required",
        "completed",
    }
    decomposition_observability = v3_objective_decomposition_observability(
        project,
        decomposition if isinstance(decomposition, dict) else {},
        project_id=project_id,
        run_id=run_id,
        requested_max_subhypotheses=max_subhypotheses,
        redecomposed=requires_v3_redecomposition,
    )
    log_event(
        "SCIENCE",
        "v3_objective_decomposition_ready",
        **decomposition_observability,
    )
    domain = str(project.get("domain") or project.get("title") or "")
    # The provider query itself stays compact, but ZhiZhi receives the entire
    # scientific brief for subspace decomposition. This preserves explicit
    # coverage requirements embedded in a user's original instruction.
    search_query = domain or str(project.get("title") or project.get("objective") or "")
    # Strip Chinese characters and non-search text from the query
    search_query = re.sub(r"[\u4e00-\u9fff]+", "", search_query).strip()
    search_query = re.sub(r"[/\|]+", " ", search_query).strip()
    search_query = re.sub(r"\s{2,}", " ", search_query).strip()
    if not search_query:
        search_query = goal or str(project.get("objective") or "")
    query = search_query
    retrieval_brief = "\n".join(
        part
        for part in (
            domain,
            str(project.get("objective") or ""),
            str(project.get("strategic_need") or ""),
            goal,
        )
        if str(part or "").strip()
    )
    turns: list[dict[str, Any]] = []
    state: dict[str, Any] = {
        "project_id": project_id,
        "groupchat_id": groupchat_id,
        "goal": query,
        "framework": "autogen_v3_groupchat",
        "workflow_mode": "V3_GROUPCHAT_ONLY",
        "orchestration_mode": "V3_GROUPCHAT_ONLY",
        "requested_autogen_run_config": requested_run_config,
        "effective_autogen_run_config": effective_run_config_payload,
        "execution_backend": "native_autogen" if use_native_autogen else "structured_executor",
        "hypothesis_id": "",
        "proposal_id": "",
        "draft_idea_id": "",
        "final_decision": "not_started",
        "socrates_verdict": "NOT_RUN",
        "mingli_blocked_reason": "",
        "active_stage": "initialization",
        "checkpoint": {
            "status": "RESUMING" if prior_checkpoint else "RUNNING",
            "resume_from_stage": resume_from_stage or "initialization",
            "completed_stages": [],
            "completed_retrieval_task_ids": prior_completed_retrieval_task_ids,
            "resumable_retrieval_task_ids": prior_resumable_retrieval_task_ids,
            "resumed_from_run_id": str((resume_record or {}).get("run_id") or ""),
            "resume_attempt": 1 + int(prior_checkpoint.get("resume_attempt") or 0),
        },
        "resumed_from_run_id": str((resume_record or {}).get("run_id") or ""),
        "resume_from_stage": resume_from_stage,
        "v3_redecomposition_applied": requires_v3_redecomposition,
        "objective_decomposition": {
            "status": decomposition.get("status") if isinstance(decomposition, dict) else "unknown",
            "sub_hypothesis_count": len(
                [
                    item for item in project.get("sub_hypotheses", [])
                    if isinstance(item, dict)
                ]
            ),
            "observability": decomposition_observability,
        },
        "research_question_cutover_audit": v3_cutover_audit,
        "research_question_contract_preflight": v3_contract_preflight,
        "retrieval_policy": {
            "schema_version": "research_question_slot_retrieval_policy_v3",
            "quota_authority": "research_question_task.slot_candidate_profile",
            "project_level_paper_quota_enabled": False,
            "source_admission_policy": "source_span_explicit_assertion_and_typed_slot_gates",
        },
    }

    def record_turn(round_name: str, speaker: str, content: Any, status: str = "completed", error: str = "") -> None:
        turns.append(
            {
                "round": round_name,
                "speaker": speaker,
                "status": status,
                "content": safe_json_output(content),
                "error": error,
                "timestamp": time.time(),
            }
        )

    log_event(
        "AUTOGEN",
        "groupchat_start",
        groupchat_id=groupchat_id,
        run_id=run_id,
        project_id=project_id,
        max_round=groupchat_spec.get("groupchat", {}).get("max_round"),
        science_dir=str(autogen_science_dir()),
    )
    if resume_record:
        log_event(
            "AUTOGEN",
            "groupchat_checkpoint_resumed",
            groupchat_id=groupchat_id,
            run_id=run_id,
            project_id=project_id,
            resumed_from_run_id=str(resume_record.get("run_id") or ""),
            resume_from_stage=resume_from_stage,
            resume_retrieval_from_checkpoint=resume_retrieval_from_checkpoint,
            completed_retrieval_task_count=len(prior_completed_retrieval_task_ids),
            resumable_retrieval_task_count=len(prior_resumable_retrieval_task_ids),
        )
    try:
        if "zhizhi" in autogen_agent_keys(groupchat_spec):
            state["active_stage"] = "zhizhi_retrieval"
            v3_retrieval_readiness = research_question_contract_declaration_summary_v3(project)
            v3_ready_set = {
                str(item)
                for item in (v3_retrieval_readiness.get("ready_sub_hypothesis_ids") or [])
                if str(item)
            }
            state["zhizhi_pending_subhypothesis_ids"] = list(
                v3_retrieval_readiness.get("pending_sub_hypothesis_ids") or []
            )
            state["research_question_retrieval_readiness"] = v3_retrieval_readiness
            state["zhizhi_skipped_blocked_subhypothesis_ids"] = []
            contracts_by_sub_id = {
                str(item.get("id") or item.get("sub_hypothesis_id") or ""): item.get(
                    "research_question_contract"
                )
                for item in project.get("sub_hypotheses", [])
                if isinstance(item, dict)
                and isinstance(item.get("research_question_contract"), dict)
            }
            reassessment_eligible = False
            for record in project.get("papergraph", []):
                if not isinstance(record, dict):
                    continue
                for sub_id in v3_ready_set:
                    contract = contracts_by_sub_id.get(sub_id)
                    if not isinstance(contract, dict):
                        continue
                    bound_task_id = next(
                        (
                            str(binding.get("research_question_task_id") or "")
                            for binding in record.get("subhypothesis_bindings", [])
                            if isinstance(binding, dict)
                            and str(binding.get("research_question_contract_id") or "")
                            == str(contract.get("contract_id") or "")
                        ),
                        "",
                    )
                    contract_state = v3_contract_binding_state(
                        record, contract, bound_task_id
                    )
                    context = (
                        record.get("import_context")
                        if isinstance(record.get("import_context"), dict)
                        else {}
                    )
                    explicitly_bound_import = (
                        str(record.get("sub_hypothesis_id") or "") == sub_id
                        or str(context.get("sub_hypothesis_id") or "") == sub_id
                        or any(
                            isinstance(binding, dict)
                            and str(binding.get("sub_hypothesis_id") or "") == sub_id
                            for binding in record.get("subhypothesis_bindings", [])
                        )
                    )
                    if (
                        (contract_state["binding"] or explicitly_bound_import)
                        and (
                            not contract_state["task_alignment"]
                            or str(
                                contract_state["task_alignment"].get("status")
                                or ""
                            ).upper() in {"NOT_EXECUTED", "TASK_SCOPE_INVALID"}
                        )
                    ):
                        reassessment_eligible = True
                        break
                if reassessment_eligible:
                    break
            reassessment: dict[str, Any] = {
                "status": "NOT_REQUIRED",
                "reassessed_count": 0,
                "skipped_records": [],
            }
            if reassessment_eligible:
                log_event(
                    "SCIENCE",
                    "v3_imported_candidate_reassessment_started",
                    project_id=project_id,
                    groupchat_id=groupchat_id,
                    run_id=run_id,
                    sub_hypothesis_ids=sorted(v3_ready_set),
                    network_retrieval_performed=False,
                )
                reassessment = reassess_v3_imported_candidates_for_contract(
                    project_id,
                    sub_hypothesis_ids=v3_ready_set,
                    use_llm=use_llm,
                )
                state["v3_imported_candidate_reassessment"] = reassessment
                log_event(
                    "SCIENCE",
                    "v3_imported_candidate_reassessment_completed",
                    project_id=project_id,
                    groupchat_id=groupchat_id,
                    run_id=run_id,
                    reassessed_count=int(reassessment.get("reassessed_count") or 0),
                    skipped_count=len(reassessment.get("skipped_records") or []),
                    network_retrieval_performed=False,
                )
                project = autogen_reload_project_state(project_id, load_project)
            def execute_current_contract_set(
                active_project: dict[str, Any],
                active_sub_hypothesis_ids: set[str],
            ) -> dict[str, Any]:
                return execute_research_question_retrieval_plans_v3(
                    project=active_project,
                    project_id=project_id,
                    sub_hypothesis_ids=active_sub_hypothesis_ids,
                    providers=list(providers),
                    use_llm=use_llm,
                    search_papers_stratified=search_papers_stratified,
                    import_literature_search_result=import_literature_search_result,
                    execute_research_question_retrieval_plan=(
                        execute_research_question_retrieval_plan
                    ),
                    groupchat_id=groupchat_id,
                    run_id=run_id,
                )

            if v3_ready_set:
                output = execute_current_contract_set(project, v3_ready_set)
                recovery_context = build_research_contract_coherence_recovery_context(
                    output
                )
                recovery_kind = str(
                    output.get("coherence_recovery_kind") or ""
                )
                if recovery_kind:
                    state["research_contract_coherence_recovery"] = {
                        **recovery_context,
                        "attempted": False,
                        "completed": False,
                    }
                if recovery_kind == "REDECOMPOSE_RESEARCH_QUESTION_CONTRACTS":
                    state["active_stage"] = "research_contract_coherence_redecomposition"
                    restart_project_from_subhypothesis_decomposition(
                        project_id,
                        reason="research_contract_coherence_recovery",
                    )
                    decomposition = json.loads(
                        decompose_research_objective(
                            project_id,
                            max_subhypotheses=max_subhypotheses,
                            use_llm=use_llm,
                            coherence_recovery_context=recovery_context,
                        )
                    )
                    state_manager.migrate_v3_research_question_state(project_id)
                    project = load_project(project_id)
                    v3_retrieval_readiness = (
                        research_question_contract_declaration_summary_v3(project)
                    )
                    v3_ready_set = {
                        str(item)
                        for item in (
                            v3_retrieval_readiness.get("ready_sub_hypothesis_ids")
                            or []
                        )
                        if str(item)
                    }
                    state["research_question_contract_preflight"] = (
                        v3_retrieval_readiness
                    )
                    state["research_question_retrieval_readiness"] = (
                        v3_retrieval_readiness
                    )
                    state["v3_redecomposition_applied"] = True
                    state["research_contract_coherence_recovery"].update({
                        "attempted": True,
                        "replacement_sub_hypothesis_ids": sorted(v3_ready_set),
                    })
                    if v3_ready_set:
                        output = execute_current_contract_set(project, v3_ready_set)
                    else:
                        output = {
                            "schema_version": "zhizhi_research_question_retrieval_execution_v3",
                            "status": "research_question_contract_revision_required",
                            "branches": [],
                            "executed_sub_hypothesis_ids": [],
                            "coherence_blocked_sub_hypothesis_ids": [],
                            "coherence_deferred_sub_hypothesis_ids": [],
                            "coherence_recovery_kind": "REVISE_RESEARCH_QUESTION_CONTRACTS",
                        }
                    state["research_contract_coherence_recovery"].update({
                        "completed": (
                            str(output.get("status") or "")
                            == "research_question_slot_retrieval_executed"
                            and not bool(
                                output.get("coherence_blocked_sub_hypothesis_ids")
                            )
                        ),
                        "replacement_status": str(output.get("status") or ""),
                        "remaining_blocked_sub_hypothesis_ids": list(
                            output.get("coherence_blocked_sub_hypothesis_ids")
                            or []
                        ),
                    })
                persisted_audits = {
                    str(branch.get("sub_hypothesis_id") or ""): dict(
                        branch.get("contract_coherence_audit") or {}
                    )
                    for branch in output.get("branches", [])
                    if isinstance(branch, dict)
                    and str(branch.get("sub_hypothesis_id") or "")
                    and isinstance(branch.get("contract_coherence_audit"), dict)
                }
                if persisted_audits:
                    project["research_contract_coherence_audits_v3"] = persisted_audits
                output.update(
                    {
                        "project_id": project_id,
                        "agent": "zhizhi",
                        "ready_sub_hypothesis_ids": sorted(v3_ready_set),
                    }
                )
                if resume_retrieval_from_checkpoint:
                    output["checkpoint_resume"] = {
                        "resumed_from_run_id": str(
                            (resume_record or {}).get("run_id") or ""
                        ),
                        "resume_from_stage": resume_from_stage,
                        "completed_retrieval_task_ids": prior_completed_retrieval_task_ids,
                        "resumable_retrieval_task_ids": prior_resumable_retrieval_task_ids,
                        "local_reassessment": reassessment,
                        "policy": (
                            "reuse only explicitly successful V3 coverage tasks; "
                            "resume failed, deferred, and still-uncovered slots"
                        ),
                    }
                    state["zhizhi_checkpoint_reused"] = dict(
                        output["checkpoint_resume"]
                    )
            else:
                output = {
                    "project_id": project_id,
                    "agent": "zhizhi",
                    "schema_version": "zhizhi_research_question_retrieval_handoff_v3",
                    "status": "research_question_contract_revision_required",
                    "blocked_sub_hypothesis_ids": sorted(
                        set(v3_retrieval_readiness.get("pending_sub_hypothesis_ids") or [])
                    ),
                    "next_step": "Correct the current ResearchQuestionContractV3 declaration; no historical causal retrieval route is available.",
                }
            record_turn("round_0_literature_reading", "ZhiZhi_ToolAgent", summarize_output(output))
            state["zhizhi_status"] = output.get("status", "completed")
            # The TanXi handoff is reference-first: do not reload PaperGraph or
            # full text after ZhiZhi merely to determine execution readiness.
            transition = autogen_reload_tanxi_transition_state(project_id)
            state["subhypothesis_retrieval_execution_order"] = (
                transition.get("subhypothesis_retrieval_execution_order")
                if isinstance(transition.get("subhypothesis_retrieval_execution_order"), dict)
                else {}
            )
            state["tanxi_transition_after_zhizhi"] = {
                "retrieval_execution_status_by_sh": dict(
                    transition.get("retrieval_execution_status_by_sh") or {}
                ),
                "subhypothesis_contract_count": int(
                    transition.get("subhypothesis_contract_count") or 0
                ),
                "retrieval_execution_count": int(
                    transition.get("retrieval_execution_count") or 0
                ),
            }
        elif "zhizhi" in autogen_agent_keys(groupchat_spec):
            state["zhizhi_status"] = "REUSED_CHECKPOINTED_RETRIEVAL"
            state["zhizhi_checkpoint_reused"] = {
                "resumed_from_run_id": str((resume_record or {}).get("run_id") or ""),
                "resume_from_stage": resume_from_stage,
                "completed_retrieval_task_ids": prior_completed_retrieval_task_ids,
                "resumable_retrieval_task_ids": prior_resumable_retrieval_task_ids,
            }
            record_turn(
                "round_0_literature_reading_resume",
                "ZhiZhi_ToolAgent",
                state["zhizhi_checkpoint_reused"],
                "reused_checkpointed_retrieval",
            )
            transition = autogen_reload_tanxi_transition_state(project_id)
            state["subhypothesis_retrieval_execution_order"] = (
                transition.get("subhypothesis_retrieval_execution_order")
                if isinstance(
                    transition.get("subhypothesis_retrieval_execution_order"), dict
                )
                else {}
            )
            state["tanxi_transition_after_zhizhi"] = {
                "retrieval_execution_status_by_sh": dict(
                    transition.get("retrieval_execution_status_by_sh") or {}
                ),
                "subhypothesis_contract_count": int(
                    transition.get("subhypothesis_contract_count") or 0
                ),
                "retrieval_execution_count": int(
                    transition.get("retrieval_execution_count") or 0
                ),
            }

        if "tanxi" in autogen_agent_keys(groupchat_spec):
            state["active_stage"] = "tanxi_gap_exploration"
            v3_branch_summary = research_question_branch_readiness_summary_v3(project)
            # Once the SH layer declares V3 research-question contracts, the
            # old corpus-size/direct-core/causal readiness contract is not a
            # permissible authority for TanXi.  Empty V3 source evidence is
            # deliberately allowed through so it can become a typed retrieval
            # shortage rather than a spurious "no gap" conclusion.
            zhizhi_branch_summary = v3_branch_summary
            ready_after_zhizhi = [
                str(item)
                for item in (
                    zhizhi_branch_summary.get(
                        "execution_ready_sub_hypothesis_ids"
                    )
                    or []
                )
                if str(item)
            ]
            coherence_deferred_after_zhizhi = [
                str(item)
                for item in (
                    zhizhi_branch_summary.get("ready_sub_hypothesis_ids") or []
                )
                if str(item) and str(item) not in ready_after_zhizhi
            ]
            pending_after_zhizhi = [
                str(item) for item in (zhizhi_branch_summary.get("pending_sub_hypothesis_ids") or []) if str(item)
            ]
            coherence_blocked_after_zhizhi = [
                str(item)
                for item in (
                    zhizhi_branch_summary.get(
                        "coherence_blocked_sub_hypothesis_ids"
                    )
                    or []
                )
                if str(item)
            ]
            domain_blocked_after_zhizhi = [
                str(item)
                for item in (
                    zhizhi_branch_summary.get(
                        "domain_blocked_sub_hypothesis_ids"
                    )
                    or []
                )
                if str(item)
            ]
            contract_coherence_blocked = bool(coherence_blocked_after_zhizhi)
            domain_contract_blocked = bool(domain_blocked_after_zhizhi)
            state["tanxi_branch_readiness"] = zhizhi_branch_summary
            if not ready_after_zhizhi:
                output = {
                    "project_id": project_id,
                    "agent": "boxue" if domain_contract_blocked else "tanxi",
                    "status": (
                        "domain_contract_repair_required"
                        if domain_contract_blocked
                        else "blocked_by_research_contract_coherence_gate"
                        if contract_coherence_blocked
                        else "blocked_by_research_question_contract_gate"
                    ),
                    "ranked_gaps": [],
                    "ready_sub_hypothesis_ids": ready_after_zhizhi,
                    "pending_sub_hypothesis_ids": pending_after_zhizhi,
                    "coherence_blocked_sub_hypothesis_ids": (
                        coherence_blocked_after_zhizhi
                    ),
                    "coherence_deferred_sub_hypothesis_ids": (
                        coherence_deferred_after_zhizhi
                    ),
                    "domain_blocked_sub_hypothesis_ids": (
                        domain_blocked_after_zhizhi
                    ),
                    "reason": (
                        "The explicit research-domain contract must be repaired before retrieval; TanXi was not started."
                        if domain_contract_blocked
                        else "Retrieval and TanXi share the same coherence gate; blocked contracts must be repaired before gap analysis."
                        if contract_coherence_blocked
                        else "V3 source-bound gap exploration requires a current research-question contract."
                    ),
                }
                log_event(
                    "AUTOGEN",
                    (
                        "tanxi_not_started_domain_contract_gate"
                        if domain_contract_blocked
                        else "tanxi_blocked_by_research_question_contract_gate"
                    ),
                    project_id=project_id,
                    ready_sub_hypotheses=len(ready_after_zhizhi),
                    pending_sub_hypotheses=len(pending_after_zhizhi),
                    domain_blocked_sub_hypotheses=len(
                        domain_blocked_after_zhizhi
                    ),
                )
                if domain_contract_blocked:
                    state["type_directed_workflow"] = {
                        "schema_version": "autogen_type_directed_routing_v2",
                        "status": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
                        "reason_code": "RESEARCH_DOMAIN_CONTRACT_NOT_READY",
                        "allowed_next_stages": [
                            "repair_research_domain_contract",
                            "resume_research_question_retrieval",
                        ],
                        "blocked_stages": [
                            "run_tanxi_gap_exploration",
                            "run_socrates_type_specific_review",
                            "build_research_package",
                            "write_research_proposal_v2",
                        ],
                        "artifact_ids": [],
                        "domain_blocked_sub_hypothesis_ids": (
                            domain_blocked_after_zhizhi
                        ),
                    }
                    state["socrates_verdict"] = (
                        "DOMAIN_CONTRACT_REPAIR_REQUIRED"
                    )
                    state["final_decision"] = "revision_required"
                    state["stop_reason"] = (
                        "Research-domain contract repair is required before "
                        "retrieval; TanXi was not started."
                    )
                elif contract_coherence_blocked:
                    state["type_directed_workflow"] = {
                        "schema_version": "autogen_type_directed_routing_v2",
                        "status": "RESEARCH_CONTRACT_COHERENCE_BLOCKED",
                        "reason_code": "CONTRACT_COHERENCE_RECOVERY_REQUIRED",
                        "allowed_next_stages": [
                            "re_decompose_or_narrow_research_question_contract",
                            "resume_contract_coherence_audit",
                        ],
                        "blocked_stages": [
                            "run_tanxi_gap_exploration",
                            "run_socrates_type_specific_review",
                            "build_research_package",
                            "write_research_proposal_v2",
                        ],
                        "artifact_ids": [],
                        "coherence_blocked_sub_hypothesis_ids": (
                            coherence_blocked_after_zhizhi
                        ),
                    }
                    state["socrates_verdict"] = (
                        "RESEARCH_CONTRACT_COHERENCE_RECOVERY_REQUIRED"
                    )
                    state["final_decision"] = "revision_required"
                    state["stop_reason"] = (
                        "Research-contract coherence recovery is required; "
                        "repeating retrieval cannot change this state."
                    )
            else:
                tanxi_mode = "llm_dual" if use_llm else "deterministic"
                try:
                    output = json.loads(
                        run_tanxi_gap_exploration(
                            project_id=project_id,
                            target_domain=domain,
                            max_gaps=10,
                            semantic_audit_mode=tanxi_mode,
                            groupchat_id=groupchat_id,
                            run_id=run_id,
                        )
                    )
                except GapSemanticAuditInvocationError as exc:
                    if tanxi_mode != "llm_dual":
                        raise
                    log_event(
                        "WARN",
                        "v2_tanxi_semantic_audit_degraded",
                        project_id=project_id,
                        groupchat_id=groupchat_id,
                        reason=f"{type(exc).__name__}: {str(exc)[:180]}",
                        recovery="same_groupchat_deterministic_tanxi_v2_rerun",
                    )
                    output = json.loads(
                        run_tanxi_gap_exploration(
                            project_id=project_id,
                            target_domain=domain,
                            max_gaps=10,
                            semantic_audit_mode="deterministic",
                            groupchat_id=groupchat_id,
                            run_id=run_id,
                        )
                    )
                    output["semantic_audit_degradation"] = {
                        "status": "LLM_DUAL_DEGRADED_TO_DETERMINISTIC_V2",
                        "reason": f"{type(exc).__name__}: {str(exc)[:180]}",
                        "groupchat_continued": True,
                    }
                output["ready_sub_hypothesis_ids"] = ready_after_zhizhi
                output["pending_sub_hypothesis_ids"] = pending_after_zhizhi
                if pending_after_zhizhi and str(output.get("status") or "") in {"", "completed"}:
                    output["status"] = "completed_with_pending_branches"
            record_turn(
                (
                    "round_0_domain_contract_repair_required"
                    if domain_contract_blocked
                    else "round_0_gap_exploration"
                ),
                (
                    "Boxue_UserProxy"
                    if domain_contract_blocked
                    else "TanXi_ToolAgent"
                ),
                summarize_output(output),
            )
            # Refresh after either a pre-TanXi gate decision or a TanXi project
            # mutation before reading any persisted gap state.
            project = autogen_reload_project_state(project_id, load_project)
            persisted_tanxi = (
                project.get("tanxi_gap_analysis")
                if isinstance(project.get("tanxi_gap_analysis"), dict)
                else {}
            )
            persisted_ranked = [
                item for item in persisted_tanxi.get("ranked_gaps", [])
                if isinstance(item, dict)
            ]
            state["gap_resolution_retrieval_pending"] = (
                v3_gap_resolution_retrieval_pending_summary(
                    [
                        item for item in project.get("gap_resolution_work_items_v3", [])
                        if isinstance(item, dict)
                    ],
                    persisted_ranked,
                )
            )
            gap_resolution_retrieval_pending = bool(
                state["gap_resolution_retrieval_pending"].get("pending")
            )
            audit_frontier_pending = bool(
                output.get("audit_continuation_pending")
                or persisted_tanxi.get("audit_continuation_pending")
            )
            state["tanxi_audit_frontier"] = {
                "pending": audit_frontier_pending,
                "continuation_frontier": [
                    item
                    for item in (
                        output.get("audit_continuation_frontier_v3")
                        or persisted_tanxi.get("audit_continuation_frontier_v3")
                        or []
                    )
                    if isinstance(item, dict)
                ],
                "resume_state_v3": dict(
                    output.get("audit_frontier_resume_state_v3")
                    or persisted_tanxi.get("audit_frontier_resume_state_v3")
                    or {}
                ),
            }
            explicit_gaps = autogen_extract_ranked_gaps(output)
            state["tanxi_gap_count"] = len(explicit_gaps)
            type_directed_report = str(output.get("schema_version") or "") == "tanxi_gap_report_v3"
            legacy_tanxi_report_rejected = False
            if (
                not type_directed_report
                and not contract_coherence_blocked
                and not domain_contract_blocked
            ):
                # The GroupChat no longer provides a compatibility lane from
                # any historical TanXi output into a causal HypothesisPackage.
                # A run must be restarted from a V3 research-question
                # contract and a current tanxi_gap_report_v3.
                state["type_directed_workflow"] = {
                    "schema_version": "autogen_type_directed_routing_v2",
                    "status": "TANXI_V2_REPORT_REQUIRED",
                    "reason_code": "LEGACY_TANXI_REPORT_REJECTED",
                    "allowed_next_stages": ["run_tanxi_gap_exploration"],
                    "blocked_stages": [
                        "build_hypothesis_packages",
                        "generate_idea",
                        "finalize_idea",
                        "run_mingli_hypothesis_evolution",
                    ],
                    "artifact_ids": [],
                }
                state["final_decision"] = "revision_required"
                record_turn(
                    "round_0_reject_legacy_tanxi_report",
                    "TanXi_ToolAgent",
                    state["type_directed_workflow"],
                    "revision_required",
                )
                # There is deliberately no historical recovery route.  The
                # code below retains a few local bookkeeping variables shared
                # by both report shapes, so mark it as type-directed only to
                # neutralise every old selector/package branch; the explicit
                # rejection state then prevents the V2 proposal path too.
                legacy_tanxi_report_rejected = True
                type_directed_report = True

            tanxi_retrieval_execution_blocked = (
                str(output.get("status") or "")
                in {
                    "RETRIEVAL_EXECUTION_FAILED_NO_CORPUS",
                    "RETRIEVAL_COMPLETED_WITHOUT_ADMITTED_EVIDENCE",
                }
            )
            if type_directed_report and tanxi_retrieval_execution_blocked:
                state["type_directed_workflow"] = {
                    "schema_version": "autogen_type_directed_routing_v2",
                    "status": str(output.get("status") or ""),
                    "reason_code": str(
                        (output.get("retrieval_diagnostic") or {}).get("reason_code")
                        or "V3_RETRIEVAL_EVIDENCE_NOT_ADMITTED"
                    ),
                    "allowed_next_stages": ["execute_research_question_retrieval_plan"],
                    "blocked_stages": [
                        "run_socrates_type_specific_review",
                        "build_research_package",
                        "write_research_proposal_v2",
                    ],
                    "artifact_ids": [],
                    "retrieval_diagnostic": dict(
                        output.get("retrieval_diagnostic") or {}
                    ),
                }
                state["socrates_verdict"] = "V3_RETRIEVAL_EXECUTION_REQUIRED"
                state["final_decision"] = "retrieval_pending"
                record_turn(
                    "round_0_retrieval_execution_required",
                    "TanXi_ToolAgent",
                    state["type_directed_workflow"],
                    "retrieval_pending",
                )

            # V3 does not reconstruct causal coverage, synthesize
            # HypothesisPackages, or write to the legacy ``hypothesis_packages``
            # collection.  TanXi V2 is the sole authority for type, maturity,
            # route, and ResearchPackage V2 dispatch.
            state["legacy_hypothesis_pipeline"] = {
                "status": "RETIRED_FOR_V3_TYPE_DIRECTED_WORKFLOW",
                "reason_code": "NO_CAUSAL_SELECTOR_OR_HYPOTHESIS_PACKAGE_FALLBACK",
            }

            if (
                type_directed_report
                and not legacy_tanxi_report_rejected
                and not tanxi_retrieval_execution_blocked
                and not contract_coherence_blocked
                and not domain_contract_blocked
            ):
                # TanXi v2 owns candidate qualification and package dispatch.
                # Do not send that result through the historical mechanism
                # selector/Socrates package lane: a measurement, boundary, or
                # theory package has its own execution mode and must retain it.
                workflow_control = (
                    project.get("research_workflow_control")
                    if isinstance(project.get("research_workflow_control"), dict)
                    else {}
                )
                primary_research = [
                    item for item in project.get("primary_research_candidates", [])
                    if isinstance(item, dict)
                ]
                research_packages = [
                    item for item in project.get("research_packages", [])
                    if isinstance(item, dict)
                ]
                socrates_admissions = [
                    autogen_primary_package_socrates_admission(item, research_packages)
                    for item in primary_research
                ]
                admitted_gap_ids = {
                    str(item.get("gap_id") or "")
                    for item in socrates_admissions
                    if item.get("allowed") is True and str(item.get("gap_id") or "")
                }
                type_dispatch = (
                    (project.get("tanxi_gap_analysis") or {}).get("research_package_candidate_dispatch")
                    if isinstance(project.get("tanxi_gap_analysis"), dict)
                    else {}
                )
                workflow_status = (
                    "TANXI_AUDIT_FRONTIER_PENDING"
                    if audit_frontier_pending
                    else str(workflow_control.get("status") or "")
                )
                workflow_reason_code = (
                    "DEFERRED_TANXI_SEMANTIC_AUDIT_FRONTIER"
                    if audit_frontier_pending
                    else str(workflow_control.get("reason_code") or "")
                )
                state["type_directed_workflow"] = {
                    "schema_version": "autogen_type_directed_routing_v2",
                    "status": workflow_status,
                    "reason_code": workflow_reason_code,
                    "allowed_next_stages": (
                        ["run_tanxi_gap_exploration"]
                        if audit_frontier_pending
                        else list(workflow_control.get("allowed_next_stages") or [])
                    ),
                    "blocked_stages": (
                        [
                            "run_socrates_type_specific_review",
                            "build_research_package",
                            "write_research_proposal_v2",
                        ]
                        if audit_frontier_pending
                        else list(workflow_control.get("blocked_stages") or [])
                    ),
                    "artifact_ids": list(workflow_control.get("artifact_ids") or []),
                    "gap_resolution_retrieval_pending": dict(
                        state.get("gap_resolution_retrieval_pending") or {}
                    ),
                    "research_package_candidate_dispatch": dict(type_dispatch or {}),
                    "research_package_ids": [
                        str(item.get("research_package_id") or "")
                        for item in project.get("research_packages", [])
                        if isinstance(item, dict) and str(item.get("research_package_id") or "")
                    ],
                    "socrates_admissions": socrates_admissions,
                }
                state["research_package_candidate_dispatch"] = dict(type_dispatch or {})
                state["type_directed_primary_research_gap_ids"] = [
                    str(item.get("gap_id") or "")
                    for item in primary_research
                    if str(item.get("gap_id") or "") in admitted_gap_ids
                ]
                state["mechanism_gap_pool"] = []
                state["best_gap_context"] = []
                state["selected_gap_count"] = 0
                state["socrates_ready_gap_ids"] = []
                state["socrates_contracts"] = {}
                type_reviews: dict[str, dict[str, Any]] = {}
                if (
                    str(workflow_control.get("status") or "") == "READY_FOR_TYPE_SPECIFIC_SOCRATES_REVIEW"
                    and not audit_frontier_pending
                    and not gap_resolution_retrieval_pending
                    and state["type_directed_primary_research_gap_ids"]
                    and "socrates" in autogen_agent_keys(groupchat_spec)
                ):
                    for gap_id in state["type_directed_primary_research_gap_ids"]:
                        try:
                            review_result = run_socrates_type_specific_review(project_id, gap_id)
                            review = (
                                json.loads(review_result)
                                if isinstance(review_result, str)
                                else dict(review_result)
                                if isinstance(review_result, dict)
                                else {}
                            )
                        except Exception as review_exc:
                            review = {
                                "schema_version": "socrates_type_review_v2",
                                "gap_id": gap_id,
                                "status": "TYPE_SPECIFIC_REVIEW_ERROR",
                                "review_ready": False,
                                "error": str(review_exc),
                            }
                        type_reviews[gap_id] = review
                        record_turn(
                            "round_0_type_specific_socrates_review_" + gap_id,
                            "Socrates_ToolAgent",
                            summarize_output(review),
                            str(review.get("status") or "completed"),
                        )
                    project = autogen_reload_project_state(project_id, load_project)
                    updated_control = (
                        project.get("research_workflow_control")
                        if isinstance(project.get("research_workflow_control"), dict)
                        else {}
                    )
                    state["type_directed_workflow"].update(
                        {
                            "status": str(updated_control.get("status") or workflow_control.get("status") or ""),
                            "reason_code": str(updated_control.get("reason_code") or workflow_control.get("reason_code") or ""),
                            "allowed_next_stages": list(updated_control.get("allowed_next_stages") or []),
                            "blocked_stages": list(updated_control.get("blocked_stages") or []),
                            "artifact_ids": list(updated_control.get("artifact_ids") or []),
                        }
                    )
                state["socrates_type_reviews"] = type_reviews
                state["socrates_verdict"] = (
                    "TYPE_SPECIFIC_REVIEWS_COMPLETED"
                    if type_reviews and all(item.get("review_ready") is True for item in type_reviews.values())
                    else "TANXI_AUDIT_FRONTIER_PENDING"
                    if audit_frontier_pending
                    else "TYPE_SPECIFIC_REVIEW_BLOCKED"
                    if type_reviews
                    else "TYPE_SPECIFIC_REVIEW_PENDING"
                    if (
                        str(workflow_control.get("status") or "") == "READY_FOR_TYPE_SPECIFIC_SOCRATES_REVIEW"
                        and not gap_resolution_retrieval_pending
                        and state["type_directed_primary_research_gap_ids"]
                    )
                    else "TYPE_SPECIFIC_PRIMARY_QUALIFICATION_REQUIRED"
                    if (
                        str(workflow_control.get("status") or "") == "READY_FOR_TYPE_SPECIFIC_SOCRATES_REVIEW"
                        and not gap_resolution_retrieval_pending
                    )
                    else "TYPE_DIRECTED_RETRIEVAL_PENDING"
                    if gap_resolution_retrieval_pending
                    or str(workflow_control.get("status") or "") == "NEEDS_TYPE_DIRECTED_RETRIEVAL"
                    else "RESEARCH_QUESTION_RETRIEVAL_PENDING"
                    if str(workflow_control.get("status") or "") in {
                        "NEEDS_RESEARCH_QUESTION_RETRIEVAL",
                        "RESEARCH_QUESTION_RETRIEVAL_PARTIAL",
                    }
                    else "TYPE_SPECIFIC_SEMANTIC_REPAIR_PENDING"
                )
                proposal_outcomes: list[dict[str, Any]] = []
                if type_reviews and all(item.get("review_ready") is True for item in type_reviews.values()):
                    # A V2 research package now continues through the generic
                    # proposal path.  It never falls back to MingLi's legacy
                    # mechanism/hypothesis schema, including for a causal
                    # package; causal identification simply selects its own
                    # proposal authoring contract.
                    for package in project.get("research_packages", []):
                        if not isinstance(package, dict):
                            continue
                        package_id = str(package.get("research_package_id") or "")
                        package_gap_id = str(package.get("gap_id") or "")
                        if not package_id or package_gap_id not in type_reviews:
                            continue
                        try:
                            brief = build_and_persist_proposal_brief(project_id, package_id)
                            if str(brief.get("schema_version") or "") != "proposal_brief_v2":
                                proposal_outcomes.append({"research_package_id": package_id, "gap_id": package_gap_id, "status": str(brief.get("status") or "blocked_proposal_brief")})
                                continue
                            draft = write_and_persist_research_proposal(project_id, str(brief.get("proposal_brief_id") or ""))
                            if str(draft.get("schema_version") or "") != "research_proposal_v2":
                                proposal_outcomes.append({"research_package_id": package_id, "proposal_brief_id": brief.get("proposal_brief_id"), "status": str(draft.get("status") or "blocked_proposal_draft")})
                                continue
                            audit = audit_and_persist_research_proposal(project_id, str(draft.get("proposal_id") or ""))
                            proposal_outcomes.append({
                                "research_package_id": package_id,
                                "proposal_brief_id": brief.get("proposal_brief_id"),
                                "proposal_id": draft.get("proposal_id"),
                                "status": str(audit.get("status") or ""),
                                "passes": audit.get("passes") is True,
                            })
                            record_turn(
                                "round_1_type_directed_proposal_" + package_id,
                                "MingLi_AssistantAgent",
                                summarize_output(audit),
                                str(audit.get("status") or "completed"),
                            )
                        except Exception as proposal_exc:
                            proposal_outcomes.append({"research_package_id": package_id, "gap_id": package_gap_id, "status": "proposal_error", "error": str(proposal_exc)})
                    project = autogen_reload_project_state(project_id, load_project)
                state["type_directed_proposal_outcomes"] = proposal_outcomes
                ready_proposals = [item for item in proposal_outcomes if item.get("passes") is True and str(item.get("proposal_id") or "")]
                state["proposal_id"] = str(ready_proposals[0].get("proposal_id") or "") if ready_proposals else ""
                state["socrates_next_step"] = dict(state["type_directed_workflow"])
                if ready_proposals:
                    state["final_decision"] = "proposal_ready"
                elif audit_frontier_pending or gap_resolution_retrieval_pending or str(workflow_control.get("status") or "") in {
                    "NEEDS_TYPE_DIRECTED_RETRIEVAL",
                    "NEEDS_RESEARCH_QUESTION_RETRIEVAL",
                    "RESEARCH_QUESTION_RETRIEVAL_PARTIAL",
                }:
                    # Retrieval work is an explicit resumable lifecycle phase,
                    # not a scientific rejection or a request to invent a new
                    # primary mechanism before its evidence has been bound.
                    state["final_decision"] = "retrieval_pending"
                else:
                    state["final_decision"] = "revision_required"
                record_turn(
                    "round_0_type_directed_package_routing",
                    "TanXi_ToolAgent",
                    state["type_directed_workflow"],
                    state["socrates_verdict"],
                )

        # V2 is a closed, type-directed pipeline.  A custom GroupChat that
        # omits TanXi (or whose TanXi response is not the V2 report) must not
        # fall through into historical mechanism selection, hypothesis drafting,
        # validation, or debate.
        if not state.get("type_directed_workflow"):
            state["active_stage"] = "type_directed_tanxi_required"
            state["socrates_verdict"] = "TYPE_DIRECTED_TANXI_REQUIRED"
            state["final_decision"] = "revision_required"
            state["stop_reason"] = (
                "A current tanxi_gap_report_v3 is required before any downstream "
                "research-package, Socrates, MingLi, validation, or debate stage."
            )
            state["type_directed_workflow"] = {
                "schema_version": "autogen_type_directed_routing_v2",
                "status": "TANXI_V2_REPORT_REQUIRED",
                "allowed_next_stages": ["run_tanxi_gap_exploration"],
                "blocked_stages": [
                    "run_socrates_type_specific_review",
                    "generate_idea",
                    "finalize_idea",
                    "run_yanzhen_mechanism_verification",
                    "run_socratic_hypothesis_debate",
                ],
                "artifact_ids": [],
            }
            record_turn(
                "round_0_type_directed_tanxi_required",
                "Boxue_LeadScientist",
                state["type_directed_workflow"],
                "revision_required",
            )

        if state["final_decision"] == "not_started":
            state["final_decision"] = "completed"
        state["active_stage"] = "completed"
        (
            completed_retrieval_task_ids,
            resumable_retrieval_task_ids,
        ) = v3_checkpoint_retrieval_task_ids(
            state.get("subhypothesis_retrieval_execution_order")
        )
        state["checkpoint"] = {
            "status": "RESUMED_COMPLETED" if prior_checkpoint else "COMPLETED",
            "resume_from_stage": resume_from_stage or "initialization",
            "completed_stages": [
                str(turn.get("round") or "")
                for turn in turns
                if isinstance(turn, dict)
                and str(turn.get("status") or "") not in {"error", "failed"}
            ],
            "completed_retrieval_task_ids": completed_retrieval_task_ids,
            "resumable_retrieval_task_ids": resumable_retrieval_task_ids,
            "resumed_from_run_id": str((resume_record or {}).get("run_id") or ""),
            "resume_attempt": 1 + int(prior_checkpoint.get("resume_attempt") or 0),
            "completed_at": time.time(),
        }
    except Exception as exc:
        record_turn("groupchat_error", "GroupChatManager", {}, "error", str(exc))
        state["final_decision"] = "error"
        state["error"] = str(exc)
        state["error_type"] = type(exc).__name__
        state["error_stage"] = str(state.get("active_stage") or "unknown")
        state["final_decision"] = "checkpointed_error"
        (
            completed_retrieval_task_ids,
            resumable_retrieval_task_ids,
        ) = v3_checkpoint_retrieval_task_ids(
            state.get("subhypothesis_retrieval_execution_order")
        )
        state["checkpoint"] = {
            "status": "CHECKPOINTED_ERROR",
            "failed_stage": state["error_stage"],
            "resume_from_stage": state["error_stage"],
            "completed_stages": [
                str(turn.get("round") or "")
                for turn in turns
                if isinstance(turn, dict) and str(turn.get("status") or "") not in {"error", "failed"}
            ],
            "completed_retrieval_task_ids": completed_retrieval_task_ids,
            "resumable_retrieval_task_ids": resumable_retrieval_task_ids,
            "error_type": state["error_type"],
            "error_message": str(exc)[:1000],
            "created_at": time.time(),
        }
        log_event(
            "ERROR",
            "groupchat_error",
            groupchat_id=groupchat_id,
            run_id=run_id,
            project_id=project_id,
            stage=state["error_stage"],
            error_type=state["error_type"],
            error=str(exc)[:500],
            science_dir=str(SCIENCE_DIR),
        )

    try:
        final_project_state = autogen_reload_project_state(project_id, load_project)
    except Exception:
        final_project_state = project if isinstance(project, dict) else {}
    final_report = autogen_final_report(final_project_state, state)
    state["final_report"] = final_report
    # ``final_report`` used to be persisted twice: once below and once inside
    # ``state``.  Keep a single canonical copy in the full run record.  The
    # in-memory state may still expose it to callers while this function is
    # finishing, but persistence does not recursively duplicate it.
    persisted_state = dict(state)
    persisted_state.pop("final_report", None)
    run_record = {
        "run_id": run_id,
        "groupchat_id": groupchat_id,
        "project_id": project_id,
        "framework": "autogen_v3_groupchat",
        "groupchat_spec": groupchat_spec,
        "state": persisted_state,
        "messages": autogen_messages_from_turns(turns),
        "turns": turns,
        "createdAt": time.time(),
        "native_autogen": native_autogen_status(use_native=use_native_autogen),
        "final_report": final_report,
        "next_step": autogen_next_step(state),
    }
    run_record["science_dir"] = str(autogen_science_dir())
    run_path = autogen_run_dir() / f"{run_id}.json"
    save_json(run_path, run_record)
    # Re-read through the canonical ScienceStateManager-backed loader only
    # after all specialist writes have completed.  The compact result must
    # report persisted state facts, not an orchestration dictionary or a
    # compressed model recollection of them.
    try:
        authoritative_project = autogen_reload_project_state(project_id, load_project)
    except Exception:
        authoritative_project = final_project_state
    summary = build_autogen_run_summary(
        run_record,
        authoritative_project=authoritative_project,
        run_path=run_path,
    )
    save_json(autogen_run_summary_path(run_id), summary)
    log_event("AUTOGEN", "groupchat_end", groupchat_id=groupchat_id, run_id=run_id, decision=state.get("final_decision"))
    return serialize_autogen_run_summary(summary)


def run_autogen_groupchat(
    project_id: str,
    goal: str = "",
    groupchat_id: str = "",
    restart_from_decomposition: bool = False,
) -> str:
    """Run the canonical V3 Boxue AutoGen GroupChat research workflow."""

    return run_autogen_research_flow(
        project_id=project_id,
        goal=goal,
        groupchat_id=groupchat_id,
        restart_from_decomposition=restart_from_decomposition,
    )


def list_autogen_groupchats(project_id: str = "") -> str:
    rows: list[dict[str, Any]] = []
    paths: list[Path] = []
    seen_dirs: set[str] = set()
    for directory in (autogen_groupchat_dir(), AUTOGEN_DIR, LEGACY_AUTOGEN_DIR):
        key = str(directory.resolve())
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        paths.extend(directory.glob("agc_*.json"))
    seen_paths: set[str] = set()
    for path in sorted(paths):
        key = path.name
        if key in seen_paths:
            continue
        seen_paths.add(key)
        payload = load_json(path)
        if project_id and payload.get("project_id") != project_id:
            continue
        rows.append(
            {
                "groupchat_id": payload.get("groupchat_id"),
                "project_id": payload.get("project_id"),
                "goal": payload.get("goal"),
                "framework": payload.get("framework"),
                "agents": [agent.get("name") for agent in payload.get("agents", [])],
                "max_round": payload.get("groupchat", {}).get("max_round"),
                "createdAt": payload.get("createdAt"),
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def get_autogen_run(run_id: str, include_details: bool = False) -> str:
    path = existing_autogen_path(
        autogen_run_dir(),
        AUTOGEN_RUN_DIR,
        run_id,
        additional_dirs=[LEGACY_AUTOGEN_RUN_DIR],
    )
    if include_details:
        return json.dumps(load_json(path), ensure_ascii=False, indent=2)

    summary_candidates = [
        path.with_name(f"{run_id}.summary.json"),
        autogen_run_summary_path(run_id),
    ]
    for summary_path in summary_candidates:
        if summary_path.exists():
            return serialize_autogen_run_summary(load_json(summary_path))

    # Backward-compatible lazy summary for runs created before compact
    # summaries existed.  Do not return the legacy multi-megabyte record.
    run_record = load_json(path)
    # A historical run must keep the version recorded at that run. Loading
    # today's project here could replace it with a later version and would
    # also parse the very large monolithic project merely to read a summary.
    summary = build_autogen_run_summary(
        run_record,
        authoritative_project=None,
        run_path=path,
    )
    return serialize_autogen_run_summary(summary)


def science_agent_to_autogen_agent(agent_key: str) -> dict[str, Any]:
    try:
        from .science_core import (
            BIANLUN_FULL_PROMPT,
            BOXUE_FULL_PROMPT,
            DUZHI_FULL_PROMPT,
            MINGLI_FULL_PROMPT,
            SCIENCE_AGENTS,
            SOCRATES_FULL_PROMPT,
            YANZHEN_FULL_PROMPT,
            ZHIZHI_FULL_PROMPT,
        )
    except ImportError:
        from science_core import (
            BIANLUN_FULL_PROMPT,
            BOXUE_FULL_PROMPT,
            DUZHI_FULL_PROMPT,
            MINGLI_FULL_PROMPT,
            SCIENCE_AGENTS,
            SOCRATES_FULL_PROMPT,
            YANZHEN_FULL_PROMPT,
            ZHIZHI_FULL_PROMPT,
        )
    prompts = {
        "boxue": BOXUE_FULL_PROMPT,
        "zhizhi": ZHIZHI_FULL_PROMPT,
        "tanxi": "You are TanXi, the Knowledge Gap Discovery AssistantAgent. Detect source-grounded, semantic-plausible, evidence-traceable gaps from PaperGraph.",
        "socrates": SOCRATES_FULL_PROMPT,
        "mingli": MINGLI_FULL_PROMPT,
        "yanzhen": YANZHEN_FULL_PROMPT,
        "duzhi": DUZHI_FULL_PROMPT,
        "bianlun": BIANLUN_FULL_PROMPT,
    }
    spec = SCIENCE_AGENTS.get(agent_key, {})
    role_map = {
        "boxue": "UserProxyAgent",
        "zhizhi": "ToolAgent",
        "tanxi": "ToolAgent",
        "socrates": "ToolAgent",
        "mingli": "AssistantAgent",
        "yanzhen": "ToolAgent",
        "duzhi": "AssistantAgent",
        "bianlun": "GroupChatManager",
    }
    return {
        "name": autogen_agent_name(agent_key),
        "key": agent_key,
        "autogen_type": role_map.get(agent_key, "AssistantAgent"),
        "role": spec.get("title") or agent_key,
        "goal": spec.get("mission") or f"Complete {agent_key} responsibilities.",
        "system_message": prompts.get(agent_key, spec.get("mission", "")),
        "llm_config_ref": autogen_llm_config_ref(agent_key),
        "tools": spec.get("tools", []),
    }


def autogen_agent_name(agent_key: str) -> str:
    return {
        "boxue": "Boxue_UserProxy",
        "zhizhi": "ZhiZhi_ToolAgent",
        "tanxi": "TanXi_ToolAgent",
        "socrates": "Socrates_ToolAgent",
        "mingli": "MingLi_Proponent",
        "yanzhen": "YanZhen_ToolAgent",
        "duzhi": "DuZhi_Opponent",
        "bianlun": "BianLun_GroupChatManager",
    }.get(agent_key, f"{agent_key}_AssistantAgent")


def autogen_llm_config_ref(agent_key: str) -> str:
    return {
        "mingli": "qwen-max",
        "duzhi": "qwen-max",
        "bianlun": "qwen-deep-research",
        "yanzhen": "qwen-deep-research",
        "zhizhi": "tool_backed_retriever",
        "tanxi": "tool_backed_gap_miner",
        "socrates": "tool_backed_mechanism_guide",
        "boxue": "human_orchestrator_proxy",
    }.get(agent_key, "qwen_default")


def build_autogen_tool_registry() -> list[dict[str, str]]:
    return [
        {"name": "decompose_research_objective", "owner": "Boxue_UserProxy"},
        {"name": "execute_research_question_retrieval_plan", "owner": "ZhiZhi_ToolAgent"},
        {"name": "run_tanxi_gap_exploration", "owner": "TanXi_ToolAgent"},
        {"name": "apply_gap_retrieval_assessment", "owner": "TanXi_ToolAgent"},
        {"name": "run_socrates_type_specific_review", "owner": "Socrates_ToolAgent"},
    ]


def build_socratic_groupchat_protocol() -> list[dict[str, Any]]:
    return [
        {"round": -1, "speaker": "Boxue_UserProxy", "objective": "Decompose the objective into typed research questions with scope tuples and source-bound evidence contracts."},
        {"round": 0, "speaker": "ZhiZhi_ToolAgent", "objective": "Execute question-slot retrieval, import versioned documents, and extract explicit source-bound assertions."},
        {"round": 0, "speaker": "TanXi_ToolAgent", "objective": "Classify source-grounded candidates by gap type, audit their source spans, and issue a type-directed retrieval plan when necessary."},
        {"round": 0, "speaker": "Socrates_ToolAgent", "objective": "Review only a qualified, type-specific research package; it may not complete missing evidence or promote a diagnostic candidate."},
        {"round": 1, "speaker": "MingLi_Proponent", "objective": "State and defend the type-appropriate research package or hypothesis."},
        {"round": 2, "speaker": "DuZhi_Opponent", "objective": "Ask Socratic clarification, evidence-contract, constraint, and counterexample questions."},
        {"round": 2, "speaker": "YanZhen_ToolAgent", "objective": "Run CAWM Layer 1 and Layer 2 evidence checks."},
        {"round": 3, "speaker": "MingLi_Proponent", "objective": "Present an experiment and falsification plan."},
        {"round": 3, "speaker": "YanZhen_ToolAgent", "objective": "Run regime-shift CAWM Layer 3."},
        {"round": 4, "speaker": "BianLun_GroupChatManager", "objective": "Synthesize refined hypothesis or revision decision."},
    ]


def native_autogen_status(*, use_native: bool) -> dict[str, Any]:
    if not use_native:
        return {
            "requested": False,
            "available": False,
            "mode": "structured_groupchat_executor",
            "reason": "Native AutoGen runtime disabled by default to control token use; v8 executes a deterministic GroupChat-compatible protocol.",
        }
    try:
        import autogen_agentchat  # noqa: F401

        return {"requested": True, "available": True, "mode": "native_autogen_agentchat_available"}
    except Exception as exc:
        try:
            import autogen  # noqa: F401

            return {"requested": True, "available": True, "mode": "native_autogen_legacy_available"}
        except Exception:
            return {"requested": True, "available": False, "mode": "structured_groupchat_executor", "reason": str(exc)}


def normalize_agent_list(agents: list[str] | None) -> list[str]:
    values = [normalize_key(item) for item in (agents or DEFAULT_AUTOGEN_AGENTS) if str(item).strip()]
    return unique_preserve_order([agent for agent in values if agent])


def autogen_agent_keys(groupchat_spec: dict[str, Any]) -> list[str]:
    return [str(agent.get("key") or "").lower() for agent in groupchat_spec.get("agents", []) if isinstance(agent, dict)]


def autogen_socrates_allows_mingli(
    verdict: Any,
    hypothesis_readiness: dict[str, Any] | None = None,
) -> bool:
    """Accept only the explicit READY_FOR_HYPOTHESIS handoff contract."""
    if str(verdict or "").strip().upper() != "READY_FOR_HYPOTHESIS":
        return False
    if not isinstance(hypothesis_readiness, dict):
        return False
    required = hypothesis_readiness.get("required")
    scientific_gate = hypothesis_readiness.get("scientific_readiness_gate")
    mode_contract = hypothesis_readiness.get("mode_contract")
    research_mode = str(hypothesis_readiness.get("research_mode") or "")
    return bool(
        hypothesis_readiness.get("ready_for_hypothesis_generation")
        and hypothesis_readiness.get("contract_status") == "READY_FOR_HYPOTHESIS"
        and isinstance(scientific_gate, dict)
        and scientific_gate.get("state") == "READY"
        and isinstance(mode_contract, dict)
        and mode_contract.get("status") == "READY"
        and isinstance(required, dict)
        and all(
            required.get(name) is True
            for name in (
                "research_mode_contract",
                "causal_variable",
                "measurement",
                "falsification",
                "comparison",
                "minimal_falsification",
                "same_project_snapshot_and_subhypothesis",
                "project_topic_alignment",
                "published_theory_or_mechanism_framework",
                "published_mode_appropriate_direct_evidence",
            )
        )
        and (
            research_mode != "CONTROLLED_INTERVENTION"
            or (required.get("intervention") is True and required.get("published_direct_experiment") is True)
        )
    )


def autogen_reload_project_state(project_id: str, loader: Any) -> dict[str, Any]:
    """Reload persisted shared state after a specialist mutates the project.

    AutoGen orchestration is serialized, but agents write through independent
    tool calls. Keeping a stale dictionary here makes a successful ZhiZhi run
    look like an empty PaperGraph to the very next GRADE gate.
    """
    project = loader(project_id)
    if not isinstance(project, dict):
        raise ValueError(f"Project reload returned invalid state for {project_id}")
    return project


def autogen_reload_tanxi_transition_state(project_id: str) -> dict[str, Any]:
    """Reload only the V2 ZhiZhi→TanXi handoff state.

    This boundary intentionally excludes PaperGraph and full text. TanXi owns
    a second, reference-first evidence read, so a generic project reload here
    is both redundant and a source of avoidable memory pressure.
    """
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    transition = science_state_manager().load_tanxi_transition_context(project_id)
    if not isinstance(transition, dict):
        raise ValueError(f"TanXi transition reload returned invalid state for {project_id}")
    return transition


def normalize_speaker_selection(value: str) -> str:
    key = normalize_key(value)
    if key in {"auto", "round_robin", "manual", "random"}:
        return key
    if key in {"roundrobin", "round-robin"}:
        return "round_robin"
    return "round_robin"


def normalize_human_input_mode(value: str) -> str:
    key = normalize_key(value).upper()
    if key in {"ALWAYS", "TERMINATE", "NEVER"}:
        return key
    return "TERMINATE"


def summarize_output(output: Any) -> Any:
    if isinstance(output, dict):
        keep = [
            "status",
            "project_id",
            "search_id",
            "hypothesis_id",
            "final_decision",
            "overall_verdict",
            "next_step",
            "import_plan",
            "action",
            "thought",
        ]
        summary = {key: output.get(key) for key in keep if key in output}
        if "debate_report" in output and isinstance(output["debate_report"], dict):
            summary["debate_report"] = {
                "debate_id": output["debate_report"].get("debate_id"),
                "final_decision": output["debate_report"].get("final_decision"),
                "unresolved_issues": output["debate_report"].get("unresolved_issues", [])[:5],
            }
        if "mechanism_fidelity_report" in output and isinstance(output["mechanism_fidelity_report"], dict):
            summary["mechanism_fidelity_report"] = {
                "overall_verdict": output["mechanism_fidelity_report"].get("overall_verdict"),
                "hypothesis_id": output["mechanism_fidelity_report"].get("hypothesis_id"),
            }
        return summary or trim_text(json.dumps(output, ensure_ascii=False), 2000)
    return trim_text(str(output), 2000)


def autogen_extract_ranked_gaps(tanxi_output: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = tanxi_output.get("ranked_gaps")
    if isinstance(ranked, list):
        return [item for item in ranked if isinstance(item, dict)]
    return []


def autogen_gap_context(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for gap in gaps:
        compact.append(
            {
                "gap_id": gap.get("gap_id"),
                "gap_type": gap.get("gap_type") or gap.get("type"),
                "description": gap.get("description"),
                "supporting_references": gap.get("supporting_references", [])[:5]
                if isinstance(gap.get("supporting_references"), list)
                else [],
                "suggested_research_path": gap.get("suggested_research_path"),
                "value_argument": gap.get("value_argument"),
                "semantic_plausibility": gap.get("semantic_plausibility", {}),
                "mechanism_issue_signal": gap.get("mechanism_issue_signal", {}),
                "mechanism_draft": gap.get("mechanism_draft", {}),
                "gap_signal": gap.get("gap_signal", {}),
                "priority_score": gap.get("priority_score"),
                "novelty_score": gap.get("novelty_score"),
                "feasibility": gap.get("feasibility"),
                "counterfactual_tree": gap.get("counterfactual_tree"),
                "tabi_chain": gap.get("tabi_chain"),
                "tabi_warrant": gap.get("tabi_warrant"),
                "tabi_claim": gap.get("tabi_claim"),
                "hypothesis_ingredients": gap.get("hypothesis_ingredients"),
                "counterfactual_leaves": gap.get("counterfactual_leaves"),
                "sub_hypothesis_id": gap.get("sub_hypothesis_id"),
                "sub_hypothesis_ids": gap.get("sub_hypothesis_ids", []),
                "gap_assessment": gap.get("gap_assessment", {}),
                "type_payload": gap.get("type_payload", {}),
                "retrieval_plan": gap.get("retrieval_plan", {}),
                "gap_class": gap.get("gap_class"),
                "missing_edge": gap.get("missing_edge", {}),
                "falsifiability_plan": gap.get("falsifiability_plan", {}),
                "source_evidence_units": [
                    {
                        "paper_id": item.get("paper_id"),
                        "source_unit_id": item.get("source_unit_id"),
                        "source_field": item.get("source_field"),
                        "source_locator": item.get("source_locator"),
                        "excerpt": str(item.get("excerpt") or "")[:500],
                    }
                    for item in gap.get("source_evidence_units", [])
                    if isinstance(item, dict)
                ][:4],
                "mechanism_evidence_bundle": gap.get("mechanism_evidence_bundle", {}),
                "alignment_qualification": gap.get("alignment_qualification", {}),
                "gap_track": gap.get("gap_track"),
                "component_bridge_gap_synthesis_ready": gap.get("component_bridge_gap_synthesis_ready"),
                "restricted_component_bridge_hypothesis_allowed": gap.get("restricted_component_bridge_hypothesis_allowed"),
                "eligible_for_restricted_bridge_hypothesis": gap.get("eligible_for_restricted_bridge_hypothesis"),
                "hypothesis_package_type": gap.get("hypothesis_package_type"),
                "claim_strength_cap": gap.get("claim_strength_cap"),
                "post_draft_socrates_enrichment_required": gap.get("post_draft_socrates_enrichment_required"),
                "final_object_claim_disclaimer": gap.get("final_object_claim_disclaimer"),
                "may_support_final_object_claim": gap.get("may_support_final_object_claim"),
            }
        )
    return compact


def autogen_current_gap_context(
    project: dict[str, Any],
    gap_ids: list[str],
) -> list[dict[str, Any]]:
    """Return current, persisted gap contexts in the same order as requested.

    TanXi's report objects are useful execution snapshots, but Socrates can
    enrich a gap and advance the project state before MingLi runs.  Resolving
    the foreign keys again prevents an orchestration snapshot from becoming a
    second, stale scientific world.
    """
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    ranked = tanxi.get("ranked_gaps") if isinstance(tanxi.get("ranked_gaps"), list) else []
    candidates = list(ranked) + list(project.get("knowledge_gaps") or [])
    by_id: dict[str, dict[str, Any]] = {}
    for gap in candidates:
        if not isinstance(gap, dict):
            continue
        gap_id = str(gap.get("gap_id") or "")
        if gap_id and gap_id not in by_id:
            by_id[gap_id] = gap
    return autogen_gap_context([
        by_id[gap_id]
        for gap_id in [str(item) for item in gap_ids if str(item)]
        if gap_id in by_id
    ])


def unique_gap_dicts(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate an orchestration pool by persisted gap foreign key."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        gap_id = str(gap.get("gap_id") or "").strip()
        if not gap_id or gap_id in seen:
            continue
        seen.add(gap_id)
        result.append(gap)
    return result


def _fragment_ids_from_design_evidence(evidence: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in (
        "supporting_fragment_refs",
        "supporting_fragment_ids",
        "fragment_refs",
        "fragment_ids",
    ):
        values = evidence.get(key)
        if isinstance(values, list):
            ids.extend(str(item) for item in values if str(item or "").strip())
    alignments = evidence.get("fragment_alignments") if isinstance(evidence.get("fragment_alignments"), list) else []
    ids.extend(
        str(item.get("fragment_id") or item.get("source_unit_id") or "")
        for item in alignments
        if isinstance(item, dict) and str(item.get("fragment_id") or item.get("source_unit_id") or "").strip()
    )
    gate = evidence.get("primary_source_span_gate") if isinstance(evidence.get("primary_source_span_gate"), dict) else {}
    for key in ("triadic_fragment_ids", "partial_fragment_ids"):
        values = gate.get(key)
        if isinstance(values, list):
            ids.extend(str(item) for item in values if str(item or "").strip())
    return list(dict.fromkeys(ids))


def compact_research_design_evidence(
    project_id: str,
    gap_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Summarize design evidence without copying fragment alignment records.

    Until P1 artifact normalization lands, the detailed object remains in the
    canonical project snapshot.  The logical reference is deliberately stable
    across the later physical split, where ScienceStateManager will resolve it
    to a dedicated artifact instead of the monolithic project JSON.
    """
    design = evidence if isinstance(evidence, dict) else {}
    supporting = _fragment_ids_from_design_evidence(design)
    competing = _compact_summary_strings(
        design.get("competing_fragment_refs") or design.get("competing_fragment_ids"),
        limit=3,
    )
    rejected = _compact_summary_strings(
        design.get("rejected_fragment_refs") or design.get("rejected_fragment_ids"),
        limit=3,
    )
    mode = str(design.get("recommended_mode") or design.get("mode") or "UNRESOLVED_RESEARCH_DESIGN")
    raw_status = str(design.get("status") or "").upper()
    status = (
        "BLOCKED"
        if mode == "UNRESOLVED_RESEARCH_DESIGN" or raw_status in {"", "UNSUPPORTED", "BLOCKED"}
        else raw_status
    )
    reason = _compact_summary_text(
        design.get("reason")
        or design.get("blocking_reason")
        or design.get("source")
        or (
            "No source-bound research design could be resolved."
            if status == "BLOCKED"
            else "Source-bound research design evidence is available by reference."
        ),
        max_chars=1_000,
    )
    return {
        "recommended_mode": mode,
        "status": status,
        "supporting_fragment_count": len(supporting),
        "supporting_fragment_refs": supporting[:3],
        "competing_fragment_refs": competing,
        "rejected_audit_fragment_refs": rejected,
        "reason": reason,
        "research_design_evidence_ref": (
            f"science-state://projects/{project_id}/gaps/{gap_id}/"
            "mechanism_evidence_bundle/research_design_evidence"
        ),
    }


def v3_autogen_final_report(project: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Summarize only current V3 contracts, retrieval executions, and routes."""

    project = project if isinstance(project, dict) else {}
    state = state if isinstance(state, dict) else {}
    execution_ledger = (
        project.get("research_question_retrieval_executions_v3")
        if isinstance(project.get("research_question_retrieval_executions_v3"), dict)
        else {}
    )
    branches: list[dict[str, Any]] = []
    for item in project.get("sub_hypotheses", []):
        if not isinstance(item, dict):
            continue
        sub_hypothesis_id = str(item.get("id") or item.get("sub_hypothesis_id") or "").strip()
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        execution = execution_ledger.get(sub_hypothesis_id)
        if not isinstance(execution, dict):
            execution = {}
        results = [row for row in execution.get("results", []) if isinstance(row, dict)]
        slot_ledger = (
            execution.get("slot_coverage_ledger")
            if isinstance(execution.get("slot_coverage_ledger"), dict)
            else {}
        )
        slot_quality = {
            str(slot): {
                "policy_verdict": str(entry.get("policy_verdict") or ""),
                "claim_readiness": str(entry.get("claim_readiness") or ""),
                "distinct_assertion_count": int(entry.get("distinct_assertion_count") or 0),
                "distinct_span_count": int(entry.get("distinct_span_count") or 0),
                "distinct_paper_count": int(entry.get("distinct_paper_count") or 0),
                "coverage_bundle_kind": str(entry.get("coverage_bundle_kind") or ""),
                "provider_dispatch_status": str(entry.get("provider_dispatch_status") or ""),
            }
            for slot, entry in slot_ledger.items()
            if isinstance(entry, dict)
        }
        underqualified_slots = sorted(
            slot
            for slot, entry in slot_ledger.items()
            if isinstance(entry, dict)
            and str(entry.get("claim_readiness") or "") != "READY"
        )
        single_source_dependency_slots = sorted(
            slot
            for slot, entry in slot_ledger.items()
            if isinstance(entry, dict)
            and int(entry.get("distinct_paper_count") or 0) == 1
            and bool((entry.get("policy") or {}).get("require_independent_confirmation"))
        )
        branches.append(
            {
                "sub_hypothesis_id": sub_hypothesis_id,
                "contract_id": str(contract.get("contract_id") or ""),
                "contract_revision": str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                ),
                "question_kind": str(
                    (contract.get("research_question") or {}).get("question_kind") or ""
                ),
                "retrieval_status": str(execution.get("status") or "NOT_EXECUTED"),
                "slot_count": len(results),
                "retrieved_source_count": sum(
                    len(row.get("source_ids") or []) for row in results
                ),
                "candidate_intake_status": str(execution.get("candidate_intake_status") or "EMPTY"),
                "alignment_status": str(execution.get("alignment_status") or "NOT_EXECUTED"),
                "admission_status": str(execution.get("admission_status") or "EMPTY"),
                "evidence_coverage_status": str(execution.get("evidence_coverage_status") or "EMPTY"),
                "required_direct_slot_ids": list(execution.get("required_direct_slot_ids") or []),
                "covered_direct_slot_ids": list(execution.get("covered_direct_slot_ids") or []),
                "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
                "direct_evidence_paper_count": int(execution.get("direct_evidence_paper_count") or 0),
                "slot_quality": slot_quality,
                "underqualified_slots": underqualified_slots,
                "single_source_dependency_slots": single_source_dependency_slots,
            }
        )
    workflow = (
        state.get("type_directed_workflow")
        if isinstance(state.get("type_directed_workflow"), dict)
        else project.get("research_workflow_control")
        if isinstance(project.get("research_workflow_control"), dict)
        else {}
    )
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    ranked_gaps = [item for item in tanxi.get("ranked_gaps", []) if isinstance(item, dict)]
    proposals = [
        item
        for item in project.get("research_proposals", [])
        if isinstance(item, dict) and item.get("lifecycle_status") == "CURRENT"
    ]
    proposal_id = str(state.get("proposal_id") or "")
    final_proposal = next(
        (item for item in proposals if str(item.get("proposal_id") or "") == proposal_id),
        {},
    )
    if not proposal_id and proposals:
        proposal_id = str(proposals[0].get("proposal_id") or "")
        final_proposal = proposals[0]
    workflow_status = str(workflow.get("status") or "")
    if proposal_id:
        stop_reason = "A reviewed V2 ResearchPackage produced an audited Proposal V2."
    elif workflow_status == "TANXI_AUDIT_FRONTIER_PENDING":
        stop_reason = (
            "TanXi has deferred current V3 type-and-contract candidates beyond "
            "this semantic-audit batch; resume the recorded audit frontier before "
            "Socrates or a revision decision."
        )
    elif workflow_status in {
        "NEEDS_RESEARCH_QUESTION_RETRIEVAL",
        "RESEARCH_QUESTION_RETRIEVAL_PARTIAL",
    }:
        stop_reason = "V3 slot retrieval completed without sufficient source-bound assertions; continue the declared question slots."
    elif workflow_status == "NEEDS_TYPE_DIRECTED_RETRIEVAL":
        stop_reason = "TanXi identified a type-specific candidate that requires its declared retrieval assessment."
    elif workflow_status == "READY_FOR_TYPE_SPECIFIC_SOCRATES_REVIEW":
        stop_reason = "A V2 ResearchPackage is ready for its type-specific Socrates review."
    elif workflow_status == "DOMAIN_CONTRACT_REPAIR_REQUIRED":
        stop_reason = (
            "The project research-domain contract must be repaired and rebound "
            "to every V3 research-question contract before literature retrieval; "
            "TanXi was not started."
        )
    else:
        stop_reason = "TanXi V2 must complete source-bound, type-directed routing before a proposal can be authored."
    return {
        "PROJECT_ID": str(project.get("project_id") or state.get("project_id") or ""),
        "STATE_VERSION": int(project.get("state_version") or 0),
        "STATE_STORE_ID": str(project.get("state_store_id") or ""),
        "FINAL_DECISION": str(state.get("final_decision") or ""),
        "STOP_REASON": stop_reason,
        "SOCRATES_STATUS": str(state.get("socrates_verdict") or "NOT_RUN"),
        "READY_GAP_IDS": [
            str(item.get("gap_id") or "")
            for item in project.get("primary_research_candidates", [])
            if isinstance(item, dict) and str(item.get("gap_id") or "")
        ],
        "FINAL_HYPOTHESIS_ID": "",
        "FINAL_PROPOSAL_ID": proposal_id,
        "PROPOSAL_STATUS": str((final_proposal.get("audit") or {}).get("status") or ""),
        "DEBATE_ITERATIONS": 0,
        "HYPOTHESIS_PACKAGE_GATE": {},
        "UNCOVERED_ANALYSIS_ROLES": [],
        "CURRENT_ALLOWED_CONCLUSION_STRENGTH": [
            "scope_bounded_research_plan"
        ] if proposal_id else [],
        "TANXI_CANDIDATE_FUNNEL": dict(
            tanxi.get("tanxi_candidate_funnel")
            or tanxi.get("candidate_funnel")
            or {}
        ),
        "TANXI_AUDIT_FRONTIER": dict(
            state.get("tanxi_audit_frontier") or {}
        ),
        "GAP_LANDSCAPE": {
            "schema_version": "gap_landscape_report_v2",
            "ranked_gap_ids": [
                str(item.get("gap_id") or "") for item in ranked_gaps if str(item.get("gap_id") or "")
            ],
            "branch_retrieval": branches,
        },
        "BLOCKED_SOURCE_GROUNDED_SEEDS": [],
        "V3_BRANCHES": branches,
        "V3_WORKFLOW_STATUS": workflow_status,
    }


def autogen_final_report(project: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Generate a run report from persisted V3 state, never a free-text guess."""
    return v3_autogen_final_report(project, state)


def autogen_messages_from_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": str(turn.get("speaker") or "unknown"),
            "role": "assistant" if "UserProxy" not in str(turn.get("speaker") or "") else "user",
            "content": json.dumps(turn.get("content", {}), ensure_ascii=False),
            "round": turn.get("round"),
            "status": turn.get("status"),
        }
        for turn in turns
    ]


def safe_json_output(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def autogen_next_step(state: dict[str, Any]) -> str:
    decision = str(state.get("final_decision") or "")
    if decision == "accept_for_experiment":
        return "Proceed to GeWu experiment planning or implementation."
    if decision == "proposal_ready":
        return "Review or export the audited type-directed Proposal V2; it is a scoped research plan, not a validated result."
    if decision in {"revision_required", "revise", "human_review"}:
        return "Inspect AutoGen GroupChat messages and regenerate or revise the hypothesis."
    if decision in {"error", "checkpointed_error"}:
        return "Resume the same V3 GroupChat checkpoint from the recorded failed stage; do not create pipeline tasks or a DAG."
    return "Review the AutoGen GroupChat run and decide whether to continue to experiment design."


def _compact_summary_text(value: Any, max_chars: int = 2_000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _compact_summary_strings(values: Any, *, limit: int = 50, max_chars: int = 256) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    compact: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_summary_text(value, max_chars=max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        compact.append(text)
        if len(compact) >= max(1, int(limit)):
            break
    return compact


def _compact_package_gate(value: Any, stop_reason: str = "") -> dict[str, Any]:
    gate = value if isinstance(value, dict) else {}
    ready_ids = _compact_summary_strings(gate.get("ready_package_ids"), limit=20)
    packages = gate.get("packages") if isinstance(gate.get("packages"), list) else []
    blocked = gate.get("blocked_packages") if isinstance(gate.get("blocked_packages"), list) else []
    reasons: list[str] = []
    for item in blocked:
        if not isinstance(item, dict):
            continue
        reasons.extend(_compact_summary_strings(item.get("reasons"), limit=3, max_chars=500))
    if not reasons:
        for item in packages:
            if not isinstance(item, dict) or item.get("ready") is True:
                continue
            reasons.extend(_compact_summary_strings(item.get("reasons"), limit=3, max_chars=500))
    status = (
        "READY"
        if ready_ids or any(isinstance(item, dict) and item.get("ready") is True for item in packages)
        else "BLOCKED"
        if blocked or packages or stop_reason
        else "NOT_EVALUATED"
    )
    reason = reasons[0] if reasons else _compact_summary_text(stop_reason, max_chars=1_000)
    return {
        "status": status,
        "reason": reason,
        "ready_package_ids": ready_ids,
        "evaluated_package_count": len(packages),
        "blocked_package_count": len(blocked) or sum(
            1 for item in packages if isinstance(item, dict) and item.get("ready") is not True
        ),
    }


def _run_artifact_ref(path: Path, json_pointer: str = "") -> str:
    try:
        relative = path.resolve().relative_to(autogen_science_dir().resolve()).as_posix()
    except (OSError, ValueError):
        relative = path.resolve().as_posix()
    return relative + (f"#{json_pointer}" if json_pointer else "")


def build_autogen_run_summary(
    run_record: dict[str, Any],
    *,
    authoritative_project: dict[str, Any] | None = None,
    run_path: Path | None = None,
) -> dict[str, Any]:
    """Build the only schema permitted to cross the tool-result boundary.

    The full run remains on disk for audit.  This whitelist deliberately does
    not copy contracts, gaps, evidence bundles, fragment alignments, research
    design evidence, messages, or turns into the coordinator context.
    """
    record = run_record if isinstance(run_record, dict) else {}
    project = authoritative_project if isinstance(authoritative_project, dict) else {}
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    report = record.get("final_report") if isinstance(record.get("final_report"), dict) else {}
    if not report and isinstance(state.get("final_report"), dict):
        # Compatibility with legacy records that stored the report only under
        # state, while still returning a compact whitelist.
        report = state["final_report"]

    run_id = str(record.get("run_id") or "")
    project_id = str(project.get("project_id") or report.get("PROJECT_ID") or record.get("project_id") or "")
    path = run_path or (autogen_run_dir() / f"{run_id}.json")
    summary_path = path.with_name(f"{run_id}.summary.json")
    allowed = report.get("CURRENT_ALLOWED_CONCLUSION_STRENGTH")
    allowed_values = _compact_summary_strings(allowed, limit=10, max_chars=256)
    stop_reason = _compact_summary_text(report.get("STOP_REASON") or state.get("stop_reason"), max_chars=2_000)
    final_hypothesis_id = str(report.get("FINAL_HYPOTHESIS_ID") or state.get("hypothesis_id") or "").strip()
    final_proposal_id = str(report.get("FINAL_PROPOSAL_ID") or state.get("proposal_id") or "").strip()
    retrieval_execution_order = (
        state.get("subhypothesis_retrieval_execution_order")
        if isinstance(state.get("subhypothesis_retrieval_execution_order"), dict)
        else project.get("subhypothesis_retrieval_execution_order")
        if isinstance(project.get("subhypothesis_retrieval_execution_order"), dict)
        else {}
    )
    summary = {
        "schema_version": AUTOGEN_RUN_SUMMARY_SCHEMA_VERSION,
        "project_id": project_id,
        "run_id": run_id,
        "groupchat_id": str(record.get("groupchat_id") or ""),
        "state_version": int(project.get("state_version") or report.get("STATE_VERSION") or 0),
        "state_store_id": str(project.get("state_store_id") or report.get("STATE_STORE_ID") or ""),
        "final_decision": str(report.get("FINAL_DECISION") or state.get("final_decision") or ""),
        "stop_reason": stop_reason,
        "socrates_status": str(report.get("SOCRATES_STATUS") or state.get("socrates_verdict") or ""),
        "ready_gap_ids": _compact_summary_strings(report.get("READY_GAP_IDS") or state.get("socrates_ready_gap_ids"), limit=50),
        "final_hypothesis_id": final_hypothesis_id or None,
        "final_proposal_id": final_proposal_id or None,
        "proposal_status": str(report.get("PROPOSAL_STATUS") or ""),
        "debate_iterations": int(report.get("DEBATE_ITERATIONS") or state.get("debate_iterations_completed") or 0),
        "hypothesis_package_gate": _compact_package_gate(report.get("HYPOTHESIS_PACKAGE_GATE"), stop_reason),
        "uncovered_analysis_roles": _compact_summary_strings(report.get("UNCOVERED_ANALYSIS_ROLES"), limit=20),
        "current_allowed_conclusion_strength": allowed_values[0] if allowed_values else "",
        "checkpoint": (
            {
                "status": str((state.get("checkpoint") or {}).get("status") or ""),
                "resume_from_stage": str((state.get("checkpoint") or {}).get("resume_from_stage") or ""),
                "failed_stage": str((state.get("checkpoint") or {}).get("failed_stage") or ""),
                "resumed_from_run_id": str((state.get("checkpoint") or {}).get("resumed_from_run_id") or ""),
                "resume_attempt": int((state.get("checkpoint") or {}).get("resume_attempt") or 0),
            }
            if isinstance(state.get("checkpoint"), dict)
            else {}
        ),
        "resumed_from_run_id": str(state.get("resumed_from_run_id") or ""),
        "v3_redecomposition_applied": bool(
            state.get("v3_redecomposition_applied") is True
        ),
        "subhypothesis_retrieval_execution_order": (
            {
                "retrieval_order": str(retrieval_execution_order.get("retrieval_order") or ""),
                "priority_strategy": str(retrieval_execution_order.get("priority_strategy") or ""),
                "ordered_sub_hypothesis_ids": _compact_summary_strings(
                    retrieval_execution_order.get("ordered_sub_hypothesis_ids"),
                    limit=50,
                ),
                "reason": _compact_summary_text(
                    retrieval_execution_order.get("reason"),
                    max_chars=500,
                ),
            }
            if retrieval_execution_order
            else {}
        ),
        "tanxi_candidate_funnel": {
            str(key): int(value)
            for key, value in (report.get("TANXI_CANDIDATE_FUNNEL") or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        "gap_landscape": (
            {
                key: {
                    str(bucket): _compact_summary_strings(values, limit=50)
                    for bucket, values in value.items()
                    if isinstance(value, dict)
                }
                for key, value in (report.get("GAP_LANDSCAPE") or {}).items()
                if key != "schema_version" and isinstance(value, dict)
            }
            if isinstance(report.get("GAP_LANDSCAPE"), dict)
            else {}
        ),
        "blocked_source_grounded_seeds": [
            {
                "gap_id": str(item.get("gap_id") or ""),
                "sub_hypothesis_id": str(item.get("sub_hypothesis_id") or ""),
                "blocked_reason": _compact_summary_text(item.get("blocked_reason"), max_chars=500),
            }
            for item in (report.get("BLOCKED_SOURCE_GROUNDED_SEEDS") or [])[:3]
            if isinstance(item, dict)
        ],
        "final_report_ref": _run_artifact_ref(path, "/final_report"),
        "run_detail_ref": _run_artifact_ref(path),
        "run_summary_ref": _run_artifact_ref(summary_path),
    }
    return summary


def serialize_autogen_run_summary(summary: dict[str, Any]) -> str:
    """Serialize a compact result and enforce the coordinator byte budget."""
    if not isinstance(summary, dict) or summary.get("schema_version") != AUTOGEN_RUN_SUMMARY_SCHEMA_VERSION:
        raise ValueError("AutoGen tool results must use autogen_run_summary_v1")
    unexpected = sorted(set(summary) - AUTOGEN_RUN_SUMMARY_FIELDS)
    if unexpected:
        raise ValueError(
            "AutoGen compact run summary contains non-schema fields; return large artifacts by reference: "
            + ", ".join(unexpected)
        )
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    byte_count = len(payload.encode("utf-8"))
    if byte_count >= MAX_AUTOGEN_TOOL_OUTPUT_BYTES:
        raise ValueError(
            "AutoGen compact run summary exceeded the 100 KB tool-output boundary: "
            f"{byte_count} bytes. Large run artifacts must be returned by reference."
        )
    return payload


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    # Keep orchestration snapshots valid even when a Windows path or a third-
    # party object reaches the run record.  Publish only after a parse check.
    json.loads(serialized)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    try:
        json.loads(temporary.read_text(encoding="utf-8"))
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def new_autogen_groupchat_id() -> str:
    return f"agc_{time.time_ns()}"


def new_autogen_run_id() -> str:
    return f"agr_{time.time_ns()}"


def normalize_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def clamp_int(value: Any, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = low
    return max(low, min(high, parsed))


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)] + "...[truncated]"
