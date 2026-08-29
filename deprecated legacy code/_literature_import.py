from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5
import ast
import hashlib
import json
import math
import re
import time
import xml.etree.ElementTree as ET

try:
    from .config import (
        SCIENCE_LLM_EXTRACTOR,
        SCIENCE_LLM_PAPER_CONTEXT_UNITS,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
        FULLTEXT_COMMIT_BATCH_SIZE,
        FULLTEXT_PREPARE_BATCH_SIZE,
        V3_RETRIEVAL_LLM_STRUCTURING_INFLIGHT,
        V3_RETRIEVAL_PREPARATION_WORKERS,
    )
    from .log import log_event
except ImportError:
    from config import (
        SCIENCE_LLM_EXTRACTOR,
        SCIENCE_LLM_PAPER_CONTEXT_UNITS,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
        FULLTEXT_COMMIT_BATCH_SIZE,
        FULLTEXT_PREPARE_BATCH_SIZE,
        V3_RETRIEVAL_LLM_STRUCTURING_INFLIGHT,
        V3_RETRIEVAL_PREPARATION_WORKERS,
    )
    from log import log_event

try:
    from ._literature_retrieval_foundation import normalize_optional_identifier
except ImportError:
    from _literature_retrieval_foundation import normalize_optional_identifier

try:
    from ._project_compaction import extraction_report_summary
except ImportError:
    from _project_compaction import extraction_report_summary

try:
    from ._type_directed_evidence import type_directed_missing_axes
    from ._evidence_slot_alignment import (
        SLOT_ALIGNMENT_SCHEMA_VERSION,
        CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
    )
    from ._evidence_admission import GAP_SOURCE_ADMISSION_SCHEMA_VERSION
except ImportError:
    from _type_directed_evidence import type_directed_missing_axes
    from _evidence_slot_alignment import (
        SLOT_ALIGNMENT_SCHEMA_VERSION,
        CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
    )
    from _evidence_admission import GAP_SOURCE_ADMISSION_SCHEMA_VERSION


def _first_optional_identifier(*values: Any) -> str:
    for value in values:
        normalized = normalize_optional_identifier(value)
        if normalized:
            return normalized
    return ""


def _process_rss_mb() -> float:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
    except (ImportError, OSError):
        return 0.0


def _serialized_json_size_bytes(value: Any) -> int:
    try:
        if isinstance(value, list):
            return 2 + sum(
                len(
                    json.dumps(
                        item,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ) + (1 if index else 0)
                for index, item in enumerate(value)
            )
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalize_external_identifiers(values: dict[str, Any] | None) -> dict[str, Any]:
    """Drop provider-neutral missing sentinels from optional external IDs."""

    normalized: dict[str, Any] = {}
    for kind, value in (values or {}).items():
        key = str(kind or "").strip()
        if not key:
            continue
        if isinstance(value, (list, tuple, set)):
            cleaned = [
                identifier
                for raw_identifier in value
                if (identifier := normalize_optional_identifier(raw_identifier))
            ]
            if cleaned:
                normalized[key] = cleaned
            continue
        identifier = normalize_optional_identifier(value)
        if identifier:
            normalized[key] = identifier
    return normalized


_OPPOSING_EVIDENCE_MARKERS = (
    "adverse",
    "reversal",
    "opposing",
    "tradeoff",
    "trade-off",
    "burden",
    "burden-shifting",
    "rebound",
    "substitution",
    "resource competition",
    "implementation failure",
    "failure mode",
    "robustness failure",
    "null effect",
    "reduced effectiveness",
    "worse",
    "harm",
    "toxicity",
    "negative mechanism",
    "adverse_or_reversal",
    "ADVERSE_OR_REVERSAL_EVIDENCE",
)

_BOUNDARY_EVIDENCE_MARKERS = (
    "boundary",
    "generalization",
    "generalisation",
    "heterogeneity",
    "moderator",
    "threshold",
    "transportability",
    "external validity",
    "boundary_or_generalization",
    "BOUNDARY_OR_NEGATIVE_EVIDENCE",
)


_V3_RETRIEVAL_LLM_STRUCTURING_SEMAPHORE = BoundedSemaphore(
    V3_RETRIEVAL_LLM_STRUCTURING_INFLIGHT
)


def _prepared_paper_id(
    commit_kwargs: Mapping[str, Any],
    existing_record: Mapping[str, Any] | None,
) -> str:
    existing_id = str((existing_record or {}).get("paper_id") or "").strip()
    if existing_id:
        return existing_id
    identity = next(
        (
            str(commit_kwargs.get(key) or "").strip()
            for key in (
                "doi", "openalex_id", "semantic_scholar_id", "arxiv_id", "url", "title"
            )
            if str(commit_kwargs.get(key) or "").strip()
        ),
        "",
    )
    if not identity:
        raise ValueError("Prepared evidence candidate requires a stable paper identity")
    return "paper_" + uuid5(NAMESPACE_URL, identity.casefold()).hex[:24]


def _prepare_document_evidence_artifact(
    *,
    project: Mapping[str, Any],
    commit_kwargs: Mapping[str, Any],
    paper_id: str,
    policy: Any,
    alignment_contract: Mapping[str, Any] | None,
    alignment_contracts: Iterable[Mapping[str, Any]] | None = None,
    existing_record: Mapping[str, Any] | None,
    preparation_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._evidence_assertions import (
            _cached_document_proposition_extraction,
            build_document_record_v4,
            extract_record_evidence_assertions,
        )
        from ._evidence_document_sections import build_document_descriptor
        from ._evidence_preparation_store import (
            load_document_proposition_artifact,
            persist_document_proposition_artifact,
            validate_prepared_evidence_path_budget,
        )
    except ImportError:
        from _evidence_assertions import (
            _cached_document_proposition_extraction,
            build_document_record_v4,
            extract_record_evidence_assertions,
        )
        from _evidence_document_sections import build_document_descriptor
        from _evidence_preparation_store import (
            load_document_proposition_artifact,
            persist_document_proposition_artifact,
            validate_prepared_evidence_path_budget,
        )
    record = deepcopy(dict(existing_record or {}))
    record.update({
        key: deepcopy(value)
        for key, value in commit_kwargs.items()
        if key not in {"project_id", "use_llm"}
    })
    record["paper_id"] = paper_id
    document_descriptor = build_document_descriptor(record)
    record["document_descriptor"] = document_descriptor
    contract_list: list[dict[str, Any]] = []
    for candidate_contract in [alignment_contract, *(alignment_contracts or [])]:
        if not isinstance(candidate_contract, Mapping):
            continue
        candidate_dict = dict(candidate_contract)
        identity = (
            str(candidate_dict.get("contract_id") or ""),
            str(candidate_dict.get("research_question_task_id") or ""),
        )
        if identity not in {
            (
                str(item.get("contract_id") or ""),
                str(item.get("research_question_task_id") or ""),
            )
            for item in contract_list
        }:
            contract_list.append(candidate_dict)
    contract = contract_list[0] if contract_list else {}
    if contract_list:
        contract_id = str(contract.get("contract_id") or "")
        revision = str(
            contract.get("contract_revision")
            or contract.get("declaration_hash")
            or ""
        )
        declaration_hash = str(
            contract.get("declaration_hash")
            or contract.get("contract_revision")
            or ""
        )
        bindings: list[dict[str, Any]] = []
        contract_ids_set: set[str] = set()
        for bound_contract in contract_list:
            bound_contract_id = str(bound_contract.get("contract_id") or "")
            bound_revision = str(
                bound_contract.get("contract_revision")
                or bound_contract.get("declaration_hash")
                or ""
            )
            bound_hash = str(
                bound_contract.get("declaration_hash")
                or bound_contract.get("contract_revision")
                or ""
            )
            if bound_contract_id:
                contract_ids_set.add(bound_contract_id)
            bindings.append({
                "sub_hypothesis_id": str(bound_contract.get("sub_hypothesis_id") or ""),
                "research_question_contract_id": bound_contract_id,
                "research_question_contract_revision": bound_revision,
                "research_question_contract_hash": bound_hash,
                "research_question_task_id": str(
                    bound_contract.get("research_question_task_id") or ""
                ),
                "target_slot_ids": [
                    str(value)
                    for value in bound_contract.get("target_slot_ids") or []
                    if str(value)
                ],
                "evidence_slot": str(
                    bound_contract.get("evidence_slot")
                    or (bound_contract.get("target_slot_ids") or [""])[0]
                    or ""
                ),
                "alignment_scope_id": str(bound_contract.get("alignment_scope_id") or ""),
                "alignment_scope_revision": str(
                    bound_contract.get("alignment_scope_revision") or ""
                ),
                "object_scope": dict(bound_contract.get("object_scope") or {}),
                "fulltext_structuring": dict(commit_kwargs.get("fulltext_structuring") or {}),
            })
        record["subhypothesis_bindings"] = bindings
        contract_ids = contract_ids_set or None
        if alignment_contracts:
            record["sh_review_context"] = {
                "schema_version": "sh_paper_review_context_v1",
                "enabled": True,
                "contract": dict(contract),
                "matched_branches": [
                    str(item.get("query_branch") or "")
                    for item in contract_list
                    if str(item.get("query_branch") or "")
                ],
                "max_spans_per_paper": 12,
            }
    else:
        contract_ids = None
    contracts = [
        item.get("research_question_contract")
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("research_question_contract"), Mapping)
        and item.get("research_question_contract", {}).get("schema_version")
        == "research_question_contract_v3"
    ]
    project_id = str(
        project.get("project_id") or commit_kwargs.get("project_id") or ""
    )
    storage_plan = validate_prepared_evidence_path_budget(
        project_id=project_id,
        paper_id=paper_id,
        document_version_id=str(document_descriptor.get("document_version_id") or ""),
    )
    log_event(
        "SCIENCE",
        "prepared_evidence_storage_ready",
        project_id=project_id,
        paper_id=paper_id,
        document_version_id=str(document_descriptor.get("document_version_id") or ""),
        layout=storage_plan["layout"],
        maximum_path_chars=storage_plan["maximum_path_chars"],
        safe_path_limit=storage_plan["safe_path_limit"],
    )
    document = build_document_record_v4(record)
    cached_preparation_bundle = load_document_proposition_artifact(
        project_id=project_id,
        paper_id=paper_id,
        document=document,
    )
    cached_proposition_artifact = (
        cached_preparation_bundle.get("document_proposition_artifact")
        if isinstance(cached_preparation_bundle, Mapping)
        and isinstance(cached_preparation_bundle.get("document_proposition_artifact"), Mapping)
        else None
    )
    if isinstance(cached_preparation_bundle, Mapping) and isinstance(cached_proposition_artifact, Mapping):
        record["document_proposition_artifact"] = dict(
            cached_proposition_artifact
        )
        record["document_sections_v5"] = list(
            cached_preparation_bundle.get("document_sections") or []
        )
        record["source_spans_v6"] = list(
            cached_preparation_bundle.get("source_spans") or []
        )
        record["contract_alignment_artifacts"] = dict(
            cached_preparation_bundle.get("contract_alignment_artifacts") or {}
        )
    decision = dict(preparation_decision or {})
    reusable_proposition_artifact = _cached_document_proposition_extraction(
        record,
        document,
        policy,
    )
    if decision.get("eligible") is False and reusable_proposition_artifact is None:
        contract_id = str(contract.get("contract_id") or "")
        task_id = str(contract.get("research_question_task_id") or "")
        role = str(decision.get("research_role") or "PENDING").upper()
        extraction_status = str(
            decision.get("extraction_status") or "EVIDENCE_PREPARATION_PENDING"
        )
        reason_codes = [
            str(item)
            for item in decision.get("reason_codes", [])
            if str(item)
        ]
        if role == "OFF_TOPIC":
            admission_level = "HARD_REJECT"
            retained_for_context = False
        elif role == "BACKGROUND":
            admission_level = "AUXILIARY"
            retained_for_context = True
        else:
            admission_level = "PROJECT_CONTEXT_ONLY"
            retained_for_context = True
        alignment = {
            "schema_version": SLOT_ALIGNMENT_SCHEMA_VERSION,
            "artifact_id": "",
            "document_version_id": str(document.get("document_version_id") or ""),
            "proposition_artifact_id": "",
            "research_question_contract_id": contract_id,
            "contract_id": contract_id,
            "contract_revision": str(
                contract.get("contract_revision")
                or contract.get("declaration_hash")
                or ""
            ),
            "research_question_task_id": task_id,
            "alignment_scope_id": str(contract.get("alignment_scope_id") or contract_id),
            "alignment_scope_revision": str(
                contract.get("alignment_scope_revision")
                or contract.get("contract_revision")
                or contract.get("declaration_hash")
                or ""
            ),
            "status": "SLOT_ALIGNMENT_NO_CANDIDATE_SPANS",
            "reason_codes": reason_codes,
            "slot_supports": [],
            "assertions": [],
        }
        admission = {
            "schema_version": GAP_SOURCE_ADMISSION_SCHEMA_VERSION,
            "research_question_contract_id": contract_id,
            "research_question_contract_revision": alignment["contract_revision"],
            "research_question_contract_hash": str(
                contract.get("declaration_hash")
                or contract.get("contract_revision")
                or ""
            ),
            "research_question_task_id": task_id,
            "admission_level": admission_level,
            "reason_codes": reason_codes,
            "deny_dominance_applied": admission_level == "HARD_REJECT",
            "retained_for_project_context": retained_for_context,
            "eligible_for_gap_synthesis": False,
            "eligible_for_direct_slot": False,
            "counts_toward_gate": False,
            "counts_toward_corpus_target": False,
            "direct_evidence_eligible": False,
            "corpus_admitted": admission_level == "AUXILIARY",
            "corpus_admission_reason": reason_codes[0] if reason_codes else "",
            "admitted_assertion_ids": [],
            "admitted_slot_support_ids": [],
            "eligible_slot_ids": [],
            "admitted_slot_supports": {},
            "extraction_status": extraction_status,
            "slot_alignment_status": alignment["status"],
        }
        return {
            "schema_version": "record_evidence_assertion_extraction_v4",
            "paper_id": paper_id,
            "document": dict(document),
            "document_descriptor": dict(document_descriptor),
            "document_sections": [],
            "source_spans": [],
            "coverage_manifest": [],
            "document_proposition_cache_status": "BYPASSED",
            "propositions": [],
            "assertion_candidates": [],
            "rejected_proposition_candidates": [],
            "assertions": [],
            "slot_supports": [],
            "contract_alignment_artifacts": ({
                contract_id: {
                    "schema_version": CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
                    "research_question_contract_id": contract_id,
                    "task_alignments": {task_id: alignment},
                    "whole_contract_alignment": {"status": "NOT_RUN"},
                }
            } if contract_id and task_id else {}),
            "gap_source_admissions_v4": ({
                contract_id: {
                    "schema_version": "contract_task_admission_index_v1",
                    "research_question_contract_id": contract_id,
                    "task_admissions": {task_id: admission},
                }
            } if contract_id and task_id else {}),
            "linked_sub_hypothesis_ids": [
                str(contract.get("sub_hypothesis_id") or "")
            ] if str(contract.get("sub_hypothesis_id") or "") else [],
            "linked_research_question_contract_ids": [contract_id] if contract_id else [],
            "unlinked_to_research_question": not bool(contract_id),
            "extraction_status": extraction_status,
            "reason_codes": reason_codes,
            "effective_policy": policy.to_dict(),
        }
    proposition_llm_started_at = time.perf_counter()
    proposition_llm_scheduled = bool(
        policy.use_llm and reusable_proposition_artifact is None
    )
    if proposition_llm_scheduled:
        enrichment = (
            record.get("full_text_enrichment")
            if isinstance(record.get("full_text_enrichment"), Mapping)
            else {}
        )
        log_event(
            "SCIENCE",
            "document_proposition_llm_started",
            project_id=project_id,
            paper_id=paper_id,
            document_version_id=str(document.get("document_version_id") or ""),
            canonical_text_chars=len(
                str(enrichment.get("canonical_text") or record.get("full_text_excerpt") or "")
            ),
            cache_status="MISS",
        )
    extracted = extract_record_evidence_assertions(
        record,
        contracts,
        policy=policy,
        contract_ids=contract_ids,
        project_id=project_id,
    )
    extracted["subhypothesis_bindings"] = [
        dict(item)
        for item in record.get("subhypothesis_bindings", [])
        if isinstance(item, Mapping)
    ]
    if proposition_llm_scheduled:
        log_event(
            "SCIENCE",
            "document_proposition_llm_completed",
            project_id=project_id,
            paper_id=paper_id,
            document_version_id=str(document.get("document_version_id") or ""),
            status=str(extracted.get("extraction_status") or ""),
            source_span_count=len(extracted.get("source_spans") or []),
            output_proposition_count=len(extracted.get("propositions") or []),
            assertion_candidate_count=len(extracted.get("assertion_candidates") or []),
            verified_assertion_count=len(extracted.get("assertions") or []),
            elapsed_ms=round(
                (time.perf_counter() - proposition_llm_started_at) * 1000,
                2,
            ),
        )
    extracted["document_descriptor"] = dict(document_descriptor)
    extracted["prepared_evidence_storage"] = storage_plan
    proposition_artifact = extracted.get("document_proposition_artifact")
    if isinstance(proposition_artifact, Mapping):
        persist_started_at = time.perf_counter()
        artifact_manifest = persist_document_proposition_artifact(
            project_id=project_id,
            paper_id=paper_id,
            artifact=proposition_artifact,
            document_descriptor=document_descriptor,
            document_sections=list(extracted.get("document_sections") or []),
            source_spans=list(extracted.get("source_spans") or []),
            contract_alignment_artifacts=dict(
                extracted.get("contract_alignment_artifacts") or {}
            ),
            document_ingestion=(
                record.get("full_text_enrichment")
                if isinstance(record.get("full_text_enrichment"), Mapping)
                else {}
            ),
        )
        extracted["document_artifact_refs"] = dict(
            artifact_manifest.get("artifact_refs") or {}
        )
        extracted["document_descriptor"] = dict(
            artifact_manifest.get("document_descriptor") or document_descriptor
        )
        log_event(
            "SCIENCE",
            "document_proposition_artifact_persisted",
            project_id=project_id,
            paper_id=paper_id,
            document_version_id=str(document.get("document_version_id") or ""),
            artifact_status=str(proposition_artifact.get("status") or ""),
            cache_status=("HIT" if cached_proposition_artifact else "MISS"),
            elapsed_ms=round(
                (time.perf_counter() - persist_started_at) * 1000,
                2,
            ),
            artifact_refs=dict(artifact_manifest.get("artifact_refs") or {}),
            serialized_artifact_bytes=sum(
                path.stat().st_size
                for path in (
                    Path(value)
                    for value in artifact_manifest.get("artifact_refs", {}).values()
                    if str(value)
                )
                if path.exists()
            ),
        )
    return extracted


def _claim_evidence_polarity_from_markers(*values: Any) -> str:
    """Normalize path/lane/role metadata into claim-facing evidence polarity."""

    text = " ".join(str(value or "") for value in values if value not in (None, "", [], {}))
    lowered = text.lower()
    if not lowered.strip():
        return "unclear"
    if "mixed" in lowered:
        return "mixed"
    if any(marker.lower() in lowered for marker in _OPPOSING_EVIDENCE_MARKERS):
        return "opposing"
    if any(marker.lower() in lowered for marker in _BOUNDARY_EVIDENCE_MARKERS):
        return "boundary"
    if any(
        marker in lowered
        for marker in (
            "supportive",
            "support",
            "core_validation",
            "causal_validation",
            "predictive_validation",
            "direct_triadic",
            "standard_core",
        )
    ):
        return "supportive"
    return "unclear"


def _papergraph_claim_effect_annotations(
    *,
    import_context: Mapping[str, Any] | None,
    alignment_assessment: Mapping[str, Any] | None,
    record_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate whether a record supports, weakens, or bounds the primary SH claim.

    The retrieval layer intentionally admits adverse evidence as in-scope.  This
    helper keeps that admission from being misread as positive support during
    later readiness, gap, and synthesis stages.
    """

    context = import_context if isinstance(import_context, Mapping) else {}
    alignment = alignment_assessment if isinstance(alignment_assessment, Mapping) else {}
    record = record_payload if isinstance(record_payload, Mapping) else {}
    type_evidence = alignment.get("type_directed_evidence") if isinstance(alignment.get("type_directed_evidence"), Mapping) else {}
    role = str(
        context.get("evidence_path_role")
        or alignment.get("evidence_path_role")
        or record.get("evidence_path_role")
        or ""
    ).strip()
    explicit_polarity = str(
        context.get("evidence_path_polarity")
        or alignment.get("evidence_path_polarity")
        or alignment.get("evidence_polarity")
        or record.get("evidence_path_polarity")
        or record.get("evidence_polarity")
        or ""
    ).strip()
    lane = str(
        context.get("target_lane")
        or alignment.get("evidence_lane")
        or type_evidence.get("evidence_lane")
        or record.get("target_lane")
        or record.get("evidence_lane")
        or ""
    ).strip()
    polarity = _claim_evidence_polarity_from_markers(
        explicit_polarity,
        role,
        lane,
        context.get("retrieval_layer_role"),
        context.get("failure_scope"),
        context.get("negative_evidence_interpretation"),
        alignment.get("causal_role"),
        alignment.get("alignment_verdict"),
    )
    if explicit_polarity.lower() in {"supportive", "opposing", "mixed", "boundary", "unclear"}:
        polarity = explicit_polarity.lower()
    if polarity == "unclear" and bool(alignment.get("core_eligible") or alignment.get("import_eligible")):
        polarity = "supportive"
    if not role:
        if polarity == "opposing":
            role = "adverse_or_reversal"
        elif polarity == "boundary":
            role = "boundary_or_generalization"
        elif str(lane).upper() == "PREDICTIVE_VALIDATION":
            role = "predictive_validation"
        elif str(lane).upper() == "MECHANISM_DISCOVERY":
            role = "mechanism_discovery"
        elif bool(alignment.get("core_eligible")):
            role = "core_validation"
    eligible = bool(alignment.get("core_eligible") or alignment.get("import_eligible"))
    supports = bool(polarity == "supportive" and eligible)
    weakens = bool(polarity == "opposing" and eligible)
    if polarity == "mixed" and eligible:
        supports = True
        weakens = True
    boundary_supported = bool(polarity == "boundary" and eligible)
    return {
        "evidence_polarity": polarity,
        "evidence_path_role": role,
        "evidence_path_polarity": explicit_polarity.lower() if explicit_polarity else polarity,
        "supports_primary_claim": supports,
        "weakens_primary_claim": weakens,
        "boundary_condition_supported": boundary_supported,
    }


_PROJECT_IDENTITY_ALIAS_KINDS = {
    "doi",
    "pmid",
    "semantic_scholar",
    "openalex",
    "arxiv",
    "title",
}


def paper_identity_alias_keys(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every exact project identity alias, including normalized title."""

    try:
        from ._literature_retrieval_foundation import canonical_paper_identity
    except ImportError:
        from _literature_retrieval_foundation import canonical_paper_identity
    identity = canonical_paper_identity(candidate)
    aliases = identity.get("aliases") if isinstance(identity.get("aliases"), dict) else {}
    return tuple(
        dict.fromkeys(
            f"{kind}:{value}"
            for kind, values in aliases.items()
            if kind in _PROJECT_IDENTITY_ALIAS_KINDS
            for value in (values if isinstance(values, list) else [])
            if str(value).strip()
        )
    )


def build_project_paper_identity_index(
    project: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index one project snapshot once for exact pre-download deduplication."""

    index: dict[str, dict[str, Any]] = {}
    papergraph = project.get("papergraph") if isinstance(project, Mapping) else []
    for record in papergraph if isinstance(papergraph, list) else []:
        if not isinstance(record, dict):
            continue
        for alias in paper_identity_alias_keys(record):
            index.setdefault(alias, record)
    return index


def register_project_paper_identity(
    identity_index: dict[str, dict[str, Any]],
    record: dict[str, Any],
) -> None:
    for alias in paper_identity_alias_keys(record):
        identity_index[alias] = record


def find_project_paper_by_identity(
    identity_index: Mapping[str, dict[str, Any]] | None,
    candidate: Mapping[str, Any],
    *,
    project: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not identity_index:
        return None
    for alias in paper_identity_alias_keys(candidate):
        existing = identity_index.get(alias)
        if isinstance(existing, dict):
            if not isinstance(project, Mapping):
                return existing
            papergraph = (
                project.get("papergraph")
                if isinstance(project.get("papergraph"), list)
                else []
            )
            if any(record is existing for record in papergraph):
                return existing
            paper_id = str(existing.get("paper_id") or existing.get("id") or "")
            unique_key = str(existing.get("unique_key") or "")
            indexed_aliases = set(paper_identity_alias_keys(existing))
            for record in papergraph:
                if not isinstance(record, dict):
                    continue
                if paper_id and paper_id == str(record.get("paper_id") or record.get("id") or ""):
                    return record
                if unique_key and unique_key == str(record.get("unique_key") or ""):
                    return record
                if indexed_aliases.intersection(paper_identity_alias_keys(record)):
                    return record
            return None
    return None


class LiteraturePreparationSingleFlight:
    """Share generic enrichment for an exact paper identity within one round."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._flights: dict[str, Future[tuple[dict[str, Any], list[str]]]] = {}

    def run(
        self,
        candidate: Mapping[str, Any],
        producer: Callable[[], tuple[dict[str, Any], list[str]]],
        *,
        flight_scope: str = "",
    ) -> tuple[dict[str, Any], list[str], bool]:
        scope = str(flight_scope or "generic")
        aliases = [
            f"{scope}:{alias}" for alias in paper_identity_alias_keys(candidate)
        ]
        owner = False
        with self._lock:
            future = next(
                (self._flights[alias] for alias in aliases if alias in self._flights),
                None,
            )
            if future is None:
                future = Future()
                owner = True
                for alias in aliases:
                    self._flights[alias] = future
        if owner:
            try:
                future.set_result(producer())
            except BaseException as exc:
                future.set_exception(exc)
                raise
        payload, sources = future.result()
        return deepcopy(payload), list(sources), not owner


def _stable_json_hash(value: Any, *, length: int = 24) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        raw = str(value)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:length]


def _alignment_contract_hash(alignment_contract: Mapping[str, Any] | None) -> str:
    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    explicit = str(contract.get("contract_hash") or "").strip()
    if explicit:
        return explicit
    return _stable_json_hash(contract, length=20)


def _normalize_v3_alignment_assessment(
    assessment: Mapping[str, Any] | None,
    alignment_contract: Mapping[str, Any] | None,
    *,
    assessment_stage: str,
) -> dict[str, Any]:
    """Attach the immutable V3 declaration identity to one completed assessment.

    The generic alignment assessor also serves non-V3 callers and therefore
    returns its traditional ``contract_hash`` field.  A
    ``ResearchQuestionContractV3`` instead uses its declaration hash as the
    versioned identity shared by bindings, assertions, admissions, and stored
    artifacts.  Normalizing at the import boundary keeps initial imports and
    later reassessments in the same audit namespace without adapting any
    legacy alignment contract.
    """

    normalized = dict(assessment or {})
    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    if (
        not normalized
        or str(contract.get("schema_version") or "")
        != "research_question_contract_v3"
    ):
        return normalized

    contract_id = str(contract.get("contract_id") or "").strip()
    contract_revision = str(contract.get("contract_revision") or "").strip()
    declaration_hash = str(contract.get("declaration_hash") or "").strip()
    if not (contract_id and contract_revision and declaration_hash):
        # An incomplete V3 declaration remains visible to the execution
        # integrity path.  Do not synthesize an identifier from an old
        # alignment hash or from unrelated scalar import state.
        return normalized

    constraint_fields = (
        "project_context",
        "subhypothesis_input",
        "mechanism_or_focus",
        "functional_outcome",
    )

    def constraint_passes(value: Any) -> bool | None:
        if isinstance(value, Mapping):
            if isinstance(value.get("passes"), bool):
                return bool(value["passes"])
            if isinstance(value.get("matched"), bool):
                return bool(value["matched"])
            return None
        if isinstance(value, bool):
            return value
        return None

    matched_constraints: list[str] = []
    missing_constraints: list[str] = []
    for field in constraint_fields:
        passed = constraint_passes(normalized.get(field))
        if passed is True:
            matched_constraints.append(field)
        elif passed is False:
            missing_constraints.append(field)
    if normalized.get("import_eligible") is True:
        decision = "ADMIT"
        reason_code = "V3_CONTRACT_ALIGNED"
    elif normalized.get("corpus_admitted") is True:
        decision = "RETAIN_NONCORE"
        reason_code = "V3_CONTRACT_NONCORE_RETAINED"
    else:
        decision = "REJECT"
        reason_code = "V3_CONTRACT_ALIGNMENT_REJECTED"
    raw_reason_codes = normalized.get("reason_codes")
    existing_reason_codes = [
        str(value).strip()
        for value in (
            raw_reason_codes
            if isinstance(raw_reason_codes, (list, tuple, set))
            else ([raw_reason_codes] if raw_reason_codes else [])
        )
        if str(value).strip()
    ]

    normalized.update(
        {
            "assessment_stage": str(assessment_stage or "v3_alignment"),
            "contract_id": contract_id,
            "research_question_contract_id": contract_id,
            "research_question_contract_revision": contract_revision,
            "research_question_contract_hash": declaration_hash,
            "contract_hash": declaration_hash,
            "decision": decision,
            "reason_codes": list(
                dict.fromkeys(
                    [
                        *existing_reason_codes,
                        reason_code,
                        *[
                            f"MISSING_{field.upper()}"
                            for field in missing_constraints
                        ],
                    ]
                )
            ),
            "matched_constraints": matched_constraints,
            "missing_constraints": missing_constraints,
            "eligible_slot_ids": [],
            "slot_eligibility_status": "PENDING_SOURCE_BOUND_ASSERTION",
        }
    )
    return normalized


def _v3_slot_candidate_scope_from_search(
    search_record: Mapping[str, Any],
    result: Mapping[str, Any],
    alignment_contract: Mapping[str, Any] | None,
    retrieval_scope: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """Return the persisted V3 task scope for import, never a legacy proxy."""

    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    if str(contract.get("schema_version") or "") != "research_question_contract_v3":
        return {}, ""

    retrieval = retrieval_scope if isinstance(retrieval_scope, Mapping) else {}
    if str(retrieval.get("kind") or "") == "subhypothesis_foundational_context":
        return {}, ""

    scope = (
        search_record.get("candidate_alignment_contract")
        if isinstance(search_record.get("candidate_alignment_contract"), Mapping)
        else {}
    )
    if str(scope.get("schema_version") or "") != "slot_candidate_scope_v3":
        return {}, "V3_SLOT_CANDIDATE_SCOPE_MISSING_FROM_SEARCH_ARTIFACT"

    expected_contract_id = str(contract.get("contract_id") or "").strip()
    expected_contract_hash = str(contract.get("declaration_hash") or "").strip()
    expected_subhypothesis_id = str(
        result.get("sub_hypothesis_id")
        or retrieval.get("sub_hypothesis_id")
        or contract.get("sub_hypothesis_id")
        or ""
    ).strip()
    expected_slot = str(result.get("evidence_slot") or "").strip()
    mismatches: list[str] = []
    if expected_contract_id and str(scope.get("research_question_contract_id") or "").strip() != expected_contract_id:
        mismatches.append("research_question_contract_id")
    if expected_contract_hash and str(scope.get("research_question_contract_hash") or "").strip() != expected_contract_hash:
        mismatches.append("research_question_contract_hash")
    if expected_subhypothesis_id and str(scope.get("sub_hypothesis_id") or "").strip() != expected_subhypothesis_id:
        mismatches.append("sub_hypothesis_id")
    if expected_slot and str(scope.get("evidence_slot") or "").strip() != expected_slot:
        mismatches.append("evidence_slot")
    if mismatches:
        return {}, "V3_SLOT_CANDIDATE_SCOPE_PROVENANCE_MISMATCH:" + ",".join(mismatches)
    return dict(scope), ""


def _v3_slot_scope_alignment_assessment(
    scope_assessment: Mapping[str, Any],
    alignment_contract: Mapping[str, Any],
    *,
    assessment_stage: str,
) -> dict[str, Any]:
    """Record V3 task-local admission without a legacy causal verdict."""

    assessment = dict(scope_assessment or {})
    contract = dict(alignment_contract or {})
    passes = bool(assessment.get("passes"))
    return {
        **assessment,
        "assessment_stage": assessment_stage,
        "contract_id": str(contract.get("contract_id") or ""),
        "research_question_contract_id": str(contract.get("contract_id") or ""),
        "research_question_contract_revision": str(contract.get("contract_revision") or ""),
        "research_question_contract_hash": str(contract.get("declaration_hash") or ""),
        "contract_hash": str(contract.get("declaration_hash") or ""),
        "decision": "ADMIT" if passes else "REJECT",
        "reason_codes": [str(assessment.get("reason_code") or "")],
        "import_eligible": passes,
        "corpus_admitted": passes,
        "corpus_admission_reason": "V3_SLOT_SCOPE_METADATA_ADMITTED" if passes else "",
        "evidence_role": "v3_slot_candidate_pending_fulltext",
        "gate_counting_evidence": False,
        "eligible_slot_ids": [],
        "slot_eligibility_status": "PENDING_SOURCE_BOUND_ASSERTION",
    }


def _v3_foundational_context_from_search(
    search_record: Mapping[str, Any],
    result: Mapping[str, Any],
    alignment_contract: Mapping[str, Any] | None,
    retrieval_scope: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """Resolve a persisted V3 foundation lane without causal alignment."""

    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    retrieval = retrieval_scope if isinstance(retrieval_scope, Mapping) else {}
    if (
        str(contract.get("schema_version") or "") != "research_question_contract_v3"
        or str(retrieval.get("kind") or "") != "subhypothesis_foundational_context"
    ):
        return {}, ""
    foundation_contract = (
        search_record.get("foundation_context_contract")
        if isinstance(search_record.get("foundation_context_contract"), Mapping)
        else {}
    )
    if str(foundation_contract.get("schema_version") or "") != "foundational_context_contract_v3":
        return {}, "V3_FOUNDATIONAL_CONTEXT_CONTRACT_MISSING_FROM_SEARCH_ARTIFACT"

    provenance = (
        search_record.get("research_question_task_provenance")
        if isinstance(search_record.get("research_question_task_provenance"), Mapping)
        else {}
    )
    expected_contract_id = str(contract.get("contract_id") or "").strip()
    expected_contract_hash = str(contract.get("declaration_hash") or "").strip()
    expected_subhypothesis_id = str(
        result.get("sub_hypothesis_id")
        or retrieval.get("sub_hypothesis_id")
        or contract.get("sub_hypothesis_id")
        or ""
    ).strip()
    mismatches: list[str] = []
    if expected_contract_id and str(provenance.get("research_question_contract_id") or "").strip() != expected_contract_id:
        mismatches.append("research_question_contract_id")
    if expected_contract_hash and str(provenance.get("research_question_contract_hash") or "").strip() != expected_contract_hash:
        mismatches.append("research_question_contract_hash")
    if expected_subhypothesis_id and str(provenance.get("sub_hypothesis_id") or "").strip() != expected_subhypothesis_id:
        mismatches.append("sub_hypothesis_id")
    if str(provenance.get("query_mode") or "").strip() != "FOUNDATIONAL_CONTEXT":
        mismatches.append("query_mode")
    if mismatches:
        return {}, "V3_FOUNDATIONAL_CONTEXT_PROVENANCE_MISMATCH:" + ",".join(mismatches)
    return dict(foundation_contract), ""


def _v3_foundational_context_alignment_assessment(
    candidate: Mapping[str, Any],
    foundation_contract: Mapping[str, Any],
    alignment_contract: Mapping[str, Any],
    *,
    assessment_stage: str,
) -> dict[str, Any]:
    """Admit a V3 foundation candidate for source-bound inspection only."""

    text = " ".join(
        str(candidate.get(field) or "").strip()
        for field in ("title", "abstract", "citation")
    ).strip()
    passes = bool(text)
    contract = dict(alignment_contract or {})
    return {
        "schema_version": "foundational_context_metadata_admission_v3",
        "assessment_stage": assessment_stage,
        "passes": passes,
        "reason_code": (
            "V3_FOUNDATIONAL_CONTEXT_METADATA_ADMITTED"
            if passes else "V3_FOUNDATIONAL_CONTEXT_TEXT_MISSING"
        ),
        "reason": (
            "V3 foundational context is admitted for full-text and source-bound assertion "
            "inspection; it cannot fill a direct evidence slot."
            if passes else "V3 foundational-context candidate has no metadata text to inspect."
        ),
        "admission_tier": "AUXILIARY_PENDING_FULLTEXT" if passes else "REJECTED",
        "pending_full_text_verification": passes,
        "detail_revalidation_required": passes,
        "evidence_admission_state": (
            "PENDING_FULLTEXT_ROLE_VERIFICATION" if passes else "REJECTED"
        ),
        "import_eligible": passes,
        "corpus_admitted": passes,
        "corpus_admission_reason": (
            "V3_FOUNDATIONAL_CONTEXT_METADATA_ADMITTED" if passes else ""
        ),
        "evidence_role": "v3_foundational_context_pending_fulltext",
        "gate_counting_evidence": False,
        "core_eligible": False,
        "direct_edge_candidate": False,
        "direct_edge_confirmed": False,
        "source_bound_hard_gate_deferred": True,
        "fulltext_review_required_for_import_or_core": True,
        "v1_causal_alignment_applied": False,
        "foundation_kind": str(foundation_contract.get("foundation_kind") or ""),
        "research_question_contract_id": str(contract.get("contract_id") or ""),
        "research_question_contract_revision": str(contract.get("contract_revision") or ""),
        "research_question_contract_hash": str(contract.get("declaration_hash") or ""),
        "contract_id": str(contract.get("contract_id") or ""),
        "contract_hash": str(contract.get("declaration_hash") or ""),
        "decision": "ADMIT" if passes else "REJECT",
        "reason_codes": [
            "V3_FOUNDATIONAL_CONTEXT_METADATA_ADMITTED"
            if passes else "V3_FOUNDATIONAL_CONTEXT_TEXT_MISSING"
        ],
        "eligible_slot_ids": [],
        "slot_eligibility_status": "PENDING_SOURCE_BOUND_ASSERTION",
    }


def _alignment_memo_paper_key(candidate: Mapping[str, Any]) -> str:
    aliases = paper_identity_alias_keys(candidate)
    if aliases:
        return str(aliases[0])
    return "title:" + _stable_json_hash(
        {
            "title": candidate.get("title"),
            "year": candidate.get("year"),
            "venue": candidate.get("venue"),
        },
        length=20,
    )


def _alignment_memo_text_hash(candidate: Mapping[str, Any], *, fulltext: bool) -> str:
    keys = (
        ("title", "abstract", "keywords", "year", "venue", "citation")
        if not fulltext
        else ("title", "abstract", "full_text_excerpt", "conclusion", "method", "results")
    )
    return _stable_json_hash({key: candidate.get(key) for key in keys}, length=20)


def _alignment_memo_key(
    candidate: Mapping[str, Any],
    alignment_contract: Mapping[str, Any] | None,
    *,
    evidence_kind: str,
    stage: str,
    fulltext: bool = False,
) -> str:
    return "|".join(
        [
            "alignment_memo_v1",
            str(stage or "metadata"),
            _alignment_contract_hash(alignment_contract),
            str(evidence_kind or ""),
            _alignment_memo_paper_key(candidate),
            _alignment_memo_text_hash(candidate, fulltext=fulltext),
        ]
    )


def _first_external_identifier(
    external_ids: Mapping[str, Any],
    *keys: str,
) -> str:
    lookup = {
        str(key or "").strip().lower(): value
        for key, value in (external_ids or {}).items()
    }
    for key in keys:
        raw = lookup.get(str(key or "").strip().lower())
        if isinstance(raw, (list, tuple, set)):
            for value in raw:
                identifier = normalize_optional_identifier(value)
                if identifier:
                    return identifier
            continue
        identifier = normalize_optional_identifier(raw)
        if identifier:
            return identifier
    return ""


def _extract_doi_from_identifier_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = normalize_doi(text)
    if re.match(r"(?i)^10\.\d{4,9}/", normalized):
        return normalized
    match = re.search(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text)
    return normalize_doi(match.group(0)) if match else ""


def full_text_resolution_seed_fields(
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, str]:
    """Return durable identifiers that justify a full-text resolver attempt."""

    external_ids: dict[str, Any] = {}
    for container in (result, payload):
        nested = (
            container.get("external_ids")
            if isinstance(container.get("external_ids"), dict)
            else container.get("externalIds")
            if isinstance(container.get("externalIds"), dict)
            else {}
        )
        external_ids.update(nested)
    doi = _first_optional_identifier(
        payload.get("doi"),
        result.get("doi"),
        _first_external_identifier(external_ids, "doi", "DOI"),
        _extract_doi_from_identifier_text(payload.get("url")),
        _extract_doi_from_identifier_text(result.get("url")),
    )
    pmc_id = _first_optional_identifier(
        payload.get("pmcid"),
        payload.get("pmc_id"),
        result.get("pmcid"),
        result.get("pmc_id"),
        _first_external_identifier(
            external_ids,
            "pmcid",
            "pmc_id",
            "pmc",
            "PMC",
            "PubMedCentral",
        ),
    )
    pmid = _first_optional_identifier(
        payload.get("pmid"),
        result.get("pmid"),
        _first_external_identifier(external_ids, "pmid", "pubmed", "PubMed"),
    )
    openalex_id = _first_optional_identifier(
        payload.get("openalex_id"),
        result.get("openalex_id"),
        _first_external_identifier(external_ids, "openalex", "OpenAlex"),
    )
    semantic_scholar_id = _first_optional_identifier(
        payload.get("semantic_scholar_id"),
        result.get("semantic_scholar_id"),
        _first_external_identifier(
            external_ids,
            "semantic_scholar",
            "SemanticScholar",
            "paperId",
            "CorpusId",
        ),
    )
    arxiv_id = _first_optional_identifier(
        payload.get("arxiv_id"),
        result.get("arxiv_id"),
        _first_external_identifier(external_ids, "arxiv", "ArXiv"),
    )
    full_text_url = _first_optional_identifier(
        payload.get("open_access_pdf"),
        result.get("open_access_pdf"),
        payload.get("pdf_url"),
        result.get("pdf_url"),
        payload.get("full_text_url"),
        result.get("full_text_url"),
    )
    repository_or_doi_url = ""
    for raw_url in (payload.get("url"), result.get("url")):
        url = str(raw_url or "").strip()
        if re.search(
            r"(?i)(doi\.org/10\.|pmc\.ncbi\.nlm\.nih\.gov|arxiv\.org|\.pdf(?:$|[?#]))",
            url,
        ):
            repository_or_doi_url = url
            break
    return {
        "doi": doi,
        "pmc_id": pmc_id,
        "pmid": pmid,
        "openalex_id": openalex_id,
        "semantic_scholar_id": semantic_scholar_id,
        "arxiv_id": arxiv_id,
        "full_text_url": full_text_url,
        "repository_or_doi_url": repository_or_doi_url,
    }


def candidate_needs_full_text_probe(
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    if str(payload.get("full_text_excerpt") or "").strip():
        return False
    seeds = full_text_resolution_seed_fields(result, payload)
    return any(str(value or "").strip() for value in seeds.values())


def _reuse_project_full_text_payload(
    payload: dict[str, Any],
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay canonical persisted full text without mutating either input."""

    reused = deepcopy(payload)
    for key in (
        "title",
        "citation",
        "authors",
        "year",
        "venue",
        "provider",
        "source_type",
        "doi",
        "pmid",
        "arxiv_id",
        "semantic_scholar_id",
        "openalex_id",
        "url",
        "abstract",
        "conclusion",
        "strengths",
        "improvements",
        "method",
        "scenario",
        "benchmark",
        "contribution",
        "limitation",
        "provider_provenance",
        "external_ids",
        "citation_metrics",
    ):
        if reused.get(key) in (None, "", [], {}) and existing.get(key) not in (None, "", [], {}):
            reused[key] = deepcopy(existing.get(key))
    reused["full_text_excerpt"] = str(existing.get("full_text_excerpt") or "")
    reused["open_access_pdf"] = str(existing.get("open_access_pdf") or "")
    enrichment = existing.get("full_text_enrichment")
    if isinstance(enrichment, dict):
        reused["_full_text_enrichment"] = deepcopy(enrichment)
    return reused


def _decomposed_project_search_scope_admission(
    project: dict[str, Any],
    project_id: str,
    search_record: dict[str, Any],
) -> dict[str, Any]:
    """Validate that a cached search may enter a decomposed project's corpus.

    This is intentionally independent of the agent runtime gate.  Imports are
    also used by pipelines and scripts, so the persisted search artifact must
    itself prove the sub-hypothesis scope rather than relying on a prompt or a
    particular tool-call path.
    """

    sub_hypotheses = project.get("sub_hypotheses") if isinstance(project.get("sub_hypotheses"), list) else []
    known_subhypothesis_ids = {
        str(item.get("id") or "").strip()
        for item in sub_hypotheses
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not known_subhypothesis_ids:
        return {"allowed": True, "kind": "undecomposed_project", "scope": {}}

    scope = search_record.get("retrieval_scope")
    scope = dict(scope) if isinstance(scope, dict) else {}
    kind = str(scope.get("kind") or "").strip()
    scope_project_id = str(scope.get("project_id") or "").strip()
    sub_hypothesis_id = str(scope.get("sub_hypothesis_id") or "").strip()
    contract_hash = str(scope.get("alignment_contract_hash") or "").strip()
    if (
        kind in {
            "subhypothesis",
            "foundational_mechanism_bridge",
            "subhypothesis_foundational_context",
        }
        and scope_project_id == project_id
        and sub_hypothesis_id in known_subhypothesis_ids
        and contract_hash
    ):
        return {"allowed": True, "kind": kind, "scope": scope}
    if (
        kind == "ad_hoc_discovery"
        and scope_project_id == project_id
        and str(scope.get("reason") or "").strip()
        and scope.get("direct_evidence_eligible") is False
    ):
        return {"allowed": True, "kind": kind, "scope": scope}
    return {
        "allowed": False,
        "kind": kind or "missing",
        "scope": scope,
        "reason_code": "SEARCH_PROVENANCE_LACKS_SUBHYPOTHESIS_SCOPE",
        "known_sub_hypothesis_ids": sorted(known_subhypothesis_ids),
    }



def assess_full_text_acquisition(record: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable full-text status; a link alone is not acquisition."""
    excerpt = str(record.get("full_text_excerpt") or "").strip()
    enrichment = record.get("full_text_enrichment") if isinstance(record.get("full_text_enrichment"), dict) else {}
    source = str(
        record.get("open_access_pdf")
        or enrichment.get("source_path")
        or enrichment.get("source_url")
        or ""
    )
    available = len(excerpt) >= 500
    resolution = (
        enrichment.get("open_access_resolution")
        if isinstance(enrichment.get("open_access_resolution"), dict)
        else record.get("_open_access_resolution")
        if isinstance(record.get("_open_access_resolution"), dict)
        else {}
    )
    attempts = [
        item for item in (resolution.get("attempts") or []) if isinstance(item, dict)
    ]
    statuses = {
        str(item.get("status") or "").strip().lower()
        for item in attempts
        if str(item.get("status") or "").strip()
    }
    http_statuses = sorted({
        int(item.get("http_status"))
        for item in attempts
        if str(item.get("http_status") or "").isdigit()
    })
    enrichment_status = str(enrichment.get("status") or "").strip().lower()
    error_text = " ".join(
        str(value or "")
        for value in (
            enrichment.get("error"),
            *(item.get("error") for item in attempts),
        )
    ).lower()
    attempted = bool(enrichment.get("attempted") or attempts)
    failure_class = "NONE"
    if not available:
        if (
            enrichment_status == "institution_auth_required"
            or "access_denied" in statuses
            or any(code in {401, 403} for code in http_statuses)
        ):
            failure_class = "ACCESS_DENIED"
        elif (
            any(code in {408, 425, 429, 500, 502, 503, 504} for code in http_statuses)
            or any(marker in error_text for marker in (
                "timeout", "timed out", "ssl", "eof", "handshake",
                "connection reset", "connection aborted", "temporarily unavailable",
            ))
        ):
            failure_class = "TRANSIENT_FETCH_FAILURE"
        elif "non_pdf" in statuses or "non-pdf" in error_text or "content-type" in error_text:
            failure_class = "NON_PDF_RESPONSE"
        elif "not_found" in statuses or 404 in http_statuses or enrichment_status == "broken_or_moved_url":
            failure_class = "NOT_FOUND"
        elif enrichment_status == "no_open_access_pdf":
            failure_class = "NO_OPEN_ACCESS_SOURCE"
        elif enrichment_status == "metadata_lookup_failed":
            failure_class = "METADATA_LOOKUP_FAILED"
        elif enrichment_status in {"no_extractable_text", "extracted", "already_present"} or source:
            failure_class = "NO_EXTRACTABLE_TEXT"
        elif enrichment_status or attempts or error_text.strip():
            failure_class = "UNKNOWN_RESOLUTION_FAILURE"
        else:
            failure_class = "NOT_ATTEMPTED"
    return {
        "full_text_available": available,
        "full_text_status": "AVAILABLE" if available else "ABSTRACT_OR_METADATA_ONLY",
        "full_text_excerpt_chars": len(excerpt),
        "full_text_source": source,
        "full_text_resolution_status": enrichment_status or str(resolution.get("status") or "").lower(),
        "full_text_resolution_attempted": attempted,
        "full_text_failure_class": failure_class,
        "full_text_failure_http_statuses": http_statuses,
    }


_FULLTEXT_STRUCTURING_ADMISSIBLE_STATUSES = {
    "structured_by_llm",
    "structured_deterministic",
    "legacy_structured",
}


def fulltext_structuring_admission_assessment(record: Mapping[str, Any]) -> dict[str, Any]:
    """Separate stored full text from full text admissible as SH evidence.

    A converted Markdown document can be safely cached before it is ready for
    PaperGraph evidence admission.  New records therefore carry an explicit
    structuring state.  Missing state is treated as legacy-complete so this
    migration does not silently invalidate evidence imported before the state
    machine existed.
    """

    full_text = assess_full_text_acquisition(dict(record))
    state = (
        dict(record.get("fulltext_structuring") or {})
        if isinstance(record.get("fulltext_structuring"), dict)
        else {}
    )
    status = str(state.get("status") or "").strip().lower()
    if not status:
        status = "legacy_structured" if full_text.get("full_text_available") else "no_fulltext"
    eligible = bool(
        full_text.get("full_text_available")
        and (
            status in _FULLTEXT_STRUCTURING_ADMISSIBLE_STATUSES
            if state
            else status == "legacy_structured"
        )
        and state.get("eligible_for_evidence_admission", True) is not False
    )
    return {
        "schema_version": "fulltext_structuring_admission_v1",
        "status": status,
        "full_text_available": bool(full_text.get("full_text_available")),
        "eligible_for_evidence_admission": eligible,
        "reason": str(state.get("reason") or ""),
        "llm_attempted": bool(state.get("llm_attempted")),
        "llm_error": str(state.get("llm_error") or ""),
        "legacy_default": not bool(state),
    }


def assess_foundational_context_v3_admission(record: Mapping[str, Any]) -> dict[str, Any]:
    """Admit a V3 foundation candidate only after source-bound extraction.

    This is deliberately a rationale-only admission.  It does not reuse the
    historic causal bridge, grant direct-primary eligibility, or fill a
    positive evidence slot.  A metadata hit, citation count, or cached PDF
    alone is insufficient.
    """

    source = dict(record) if isinstance(record, Mapping) else {}
    context = source.get("import_context") if isinstance(source.get("import_context"), dict) else {}
    scope = context.get("retrieval_scope") if isinstance(context.get("retrieval_scope"), dict) else {}
    is_foundation = bool(
        str(scope.get("kind") or "") == "subhypothesis_foundational_context"
        or str(source.get("evidence_kind") or "").lower() == "foundational_context"
    )
    if not is_foundation:
        return {
            "status": "NOT_V3_FOUNDATIONAL_CONTEXT",
            "admitted": False,
            "reason": "record was not retrieved through the V3 foundational-context lane",
        }
    fulltext = fulltext_structuring_admission_assessment(source)
    if not fulltext.get("eligible_for_evidence_admission"):
        return {
            "status": "PENDING_V3_CONTEXT_ADMISSION",
            "admitted": False,
            "reason": "acquired and structurally admissible full text is required",
        }
    sub_hypothesis_id = str(
        source.get("sub_hypothesis_id") or context.get("sub_hypothesis_id") or ""
    ).strip()
    assertions = [
        item
        for item in source.get("evidence_assertions_v4", [])
        if isinstance(item, dict)
        and list(item.get("source_span_ids") or [])
        and str(item.get("research_question_contract_id") or "").strip()
        and (
            not sub_hypothesis_id
            or str(item.get("sub_hypothesis_id") or "").strip() == sub_hypothesis_id
        )
    ]
    if not assertions:
        return {
            "status": "PENDING_V3_CONTEXT_ADMISSION",
            "admitted": False,
            "reason": "no explicit source-bound V3 assertion is available for the declared SH",
        }
    return {
        "status": "ADMITTED_V3_FOUNDATIONAL_CONTEXT",
        "admitted": True,
        "reason": "full text, source spans, and explicit V3 assertions are available",
        "admission_role": "FOUNDATIONAL_CONTEXT",
        "stratified_layer": "L1_milestone",
        "assertion_ids": [
            str(item.get("assertion_id") or "")
            for item in assertions
            if str(item.get("assertion_id") or "")
        ],
        "counts_as_direct_primary_evidence": False,
        "counts_toward_core_slot_readiness": False,
    }


def fulltext_llm_structuring_eligibility(
    *,
    acquired_full_text: bool,
    post_alignment: Mapping[str, Any] | None,
    paper_genre_assessment: Mapping[str, Any] | None,
    bridge_approved: bool,
    post_fulltext_admission: Mapping[str, Any] | None,
    reused_project_full_text: bool,
    batch_single_flight_reused: bool = False,
) -> dict[str, Any]:
    """Decide whether a newly resolved document warrants LLM structuring.

    The decision deliberately happens *after* deterministic full-text genre
    and contract alignment.  It cannot broaden layer or direct-core policy;
    it only controls whether a qualifying document may spend LLM capacity.
    """

    alignment = dict(post_alignment or {})
    genre = dict(paper_genre_assessment or {})
    admission = dict(post_fulltext_admission or {})
    if not acquired_full_text:
        return {
            "eligible": False,
            "reason": "no_acquired_fulltext",
            "role": "metadata_only",
        }
    if reused_project_full_text or batch_single_flight_reused:
        return {
            "eligible": False,
            "reason": "duplicate_fulltext_reuse",
            "role": "duplicate_reuse_skip",
        }
    if bridge_approved and not admission.get("foundation_revoked"):
        return {
            "eligible": True,
            "reason": "qualified_foundational_mechanism_bridge",
            "role": "foundational_bridge",
        }
    if not alignment:
        return {
            "eligible": False,
            "reason": "alignment_contract_or_assessment_missing",
            "role": "alignment_not_executed",
        }
    if alignment.get("import_eligible") is True:
        return {
            "eligible": True,
            "reason": "deterministically_aligned_direct_or_auxiliary_evidence",
            "role": (
                "direct_or_auxiliary_review"
                if genre.get("is_review")
                else "direct_or_auxiliary"
            ),
        }
    return {
        "eligible": False,
        "reason": "deterministic_fulltext_alignment_rejected_or_background_only",
        "role": "rejected_or_background_skip",
    }


def document_proposition_preparation_decision(
    *,
    acquired_full_text: bool,
    research_role: str,
    classification_status: str,
    contract_bound: bool,
) -> dict[str, Any]:
    role = str(research_role or "PENDING").upper()
    classification = str(classification_status or "CLASSIFICATION_PENDING").upper()
    if not acquired_full_text:
        return {
            "eligible": False,
            "alignment_ready": False,
            "research_role": role,
            "extraction_status": "FULLTEXT_UNAVAILABLE",
            "reason_codes": ["FULLTEXT_REQUIRED_FOR_DOCUMENT_PROPOSITIONS"],
        }
    if not contract_bound:
        return {
            "eligible": True,
            "alignment_ready": False,
            "research_role": role,
            "extraction_status": "PROPOSITION_SCHEDULED",
            "reason_codes": [],
            "alignment_reason_codes": ["RESEARCH_QUESTION_CONTRACT_NOT_BOUND"],
        }
    if classification != "CLASSIFIED":
        return {
            "eligible": True,
            "alignment_ready": True,
            "research_role": role,
            "extraction_status": "PROPOSITION_SCHEDULED",
            "reason_codes": [],
            "admission_reason_codes": ["PAPER_CLASSIFICATION_PENDING"],
        }
    if role == "PENDING":
        return {
            "eligible": True,
            "alignment_ready": True,
            "research_role": role,
            "extraction_status": "PROPOSITION_SCHEDULED",
            "reason_codes": [],
            "admission_reason_codes": ["RESEARCH_ROLE_PENDING"],
        }
    return {
        "eligible": True,
        "alignment_ready": True,
        "research_role": role,
        "extraction_status": "PROPOSITION_SCHEDULED",
        "reason_codes": [],
        "alignment_reason_codes": [],
    }


_EVIDENCE_GATE_BOOLEAN_FIELDS = (
    "counts_toward_gate",
    "gate_counting_evidence",
    "fulltext_evidence_admissible",
    "direct_evidence_eligible",
    "core_eligible",
    "counts_toward_corpus_target",
    "corpus_target_counting_evidence",
    "eligible_for_gap_synthesis",
    "eligible_for_direct_slot",
)


def apply_evidence_status_dominance(
    *targets: dict[str, Any] | None,
    status: str,
    reason_codes: list[str] | tuple[str, ...] = (),
) -> None:
    """Make an incomplete preparation/alignment state dominate every gate flag."""

    normalized_reasons = [str(item) for item in reason_codes if str(item)]

    def visit(value: Any, *, root: bool = False) -> None:
        if isinstance(value, dict):
            for field in _EVIDENCE_GATE_BOOLEAN_FIELDS:
                if root or field in value:
                    value[field] = False
            for child in list(value.values()):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for target in targets:
        if not isinstance(target, dict):
            continue
        visit(target, root=True)
        target["evidence_preparation_status"] = str(status)
        target["evidence_preparation_reason_codes"] = list(normalized_reasons)


def _prepared_commit_protocol_error(
    *,
    prepared_paper_id: str,
    document_descriptor: Mapping[str, Any] | None,
    prepared_evidence_artifact: Mapping[str, Any] | None,
) -> str:
    try:
        from ._evidence_document_sections import validate_document_descriptor
        from ._evidence_proposition_extraction import (
            EVIDENCE_UNIT_REGISTRY_REVISION,
            PROPOSITION_COMPOSITION_PROMPT_REVISION,
            PROPOSITION_EXTRACTION_SCHEMA_VERSION,
            PROPOSITION_PROMPT_REVISION,
            _source_span_cache_key,
        )
        from ._evidence_spans import SOURCE_SPAN_SCHEMA_VERSION
    except ImportError:
        from _evidence_document_sections import validate_document_descriptor
        from _evidence_proposition_extraction import (
            EVIDENCE_UNIT_REGISTRY_REVISION,
            PROPOSITION_COMPOSITION_PROMPT_REVISION,
            PROPOSITION_EXTRACTION_SCHEMA_VERSION,
            PROPOSITION_PROMPT_REVISION,
            _source_span_cache_key,
        )
        from _evidence_spans import SOURCE_SPAN_SCHEMA_VERSION

    if not isinstance(prepared_evidence_artifact, Mapping):
        return "PREPARED_DOCUMENT_PROPOSITION_ARTIFACT_REQUIRED"
    prepared_descriptor_raw = prepared_evidence_artifact.get("document_descriptor")
    if not isinstance(document_descriptor, Mapping) or not isinstance(
        prepared_descriptor_raw, Mapping
    ):
        return "PREPARED_ARTIFACT_PROTOCOL_MISMATCH"
    expected_paper_id = str(
        prepared_paper_id
        or document_descriptor.get("paper_id")
        or prepared_descriptor_raw.get("paper_id")
        or ""
    )
    try:
        materialized_descriptor = validate_document_descriptor(
            document_descriptor,
            paper_id=expected_paper_id,
        )
        prepared_descriptor = validate_document_descriptor(
            prepared_descriptor_raw,
            paper_id=expected_paper_id,
        )
    except ValueError:
        return "PREPARED_ARTIFACT_PROTOCOL_MISMATCH"
    descriptor_identity = (
        "paper_id",
        "document_id",
        "document_version_id",
        "document_version_hash",
        "extractor_revision",
    )
    if any(
        str(materialized_descriptor.get(key) or "")
        != str(prepared_descriptor.get(key) or "")
        for key in descriptor_identity
    ):
        return "PREPARED_ARTIFACT_PROTOCOL_MISMATCH"
    prepared_document = prepared_evidence_artifact.get("document")
    if not isinstance(prepared_document, Mapping) or str(
        prepared_document.get("paper_id") or ""
    ) != expected_paper_id:
        return "PREPARED_ARTIFACT_PROTOCOL_MISMATCH"
    document_version_id = str(prepared_descriptor.get("document_version_id") or "")
    document_version_hash = str(prepared_descriptor.get("document_version_hash") or "")
    if any((
        str(prepared_evidence_artifact.get("schema_version") or "")
        != "record_evidence_assertion_extraction_v4",
        str(prepared_document.get("document_version_id") or "") != document_version_id,
        str(prepared_document.get("document_version_hash") or "") != document_version_hash,
    )):
        return "PREPARED_EXTRACTION_SCHEMA_INVALID"
    source_spans = prepared_evidence_artifact.get("source_spans")
    if not isinstance(source_spans, list):
        return "PREPARED_SOURCE_SPAN_SET_INVALID"
    for span in source_spans:
        if not isinstance(span, Mapping) or any((
            str(span.get("schema_version") or "") != SOURCE_SPAN_SCHEMA_VERSION,
            str(span.get("paper_id") or "") != expected_paper_id,
            str(span.get("document_version_hash") or "") != document_version_hash,
            not str(span.get("source_span_id") or ""),
        )):
            return "PREPARED_SOURCE_SPAN_PROTOCOL_INVALID"
    proposition_artifact = prepared_evidence_artifact.get("document_proposition_artifact")
    extraction_status = str(prepared_evidence_artifact.get("extraction_status") or "")
    proposition_required = bool(source_spans) or extraction_status not in {
        "",
        "FULLTEXT_UNAVAILABLE",
    }
    if proposition_required and not isinstance(proposition_artifact, Mapping):
        return "PREPARED_DOCUMENT_PROPOSITION_ARTIFACT_REQUIRED"
    if isinstance(proposition_artifact, Mapping):
        if any((
            str(proposition_artifact.get("schema_version") or "")
            != PROPOSITION_EXTRACTION_SCHEMA_VERSION,
            str(proposition_artifact.get("prompt_revision") or "")
            != PROPOSITION_PROMPT_REVISION,
            str(proposition_artifact.get("evidence_unit_registry_revision") or "")
            != EVIDENCE_UNIT_REGISTRY_REVISION,
            str(proposition_artifact.get("composition_prompt_revision") or "")
            != PROPOSITION_COMPOSITION_PROMPT_REVISION,
            str(proposition_artifact.get("document_version_id") or "")
            != document_version_id,
            str(proposition_artifact.get("document_version_hash") or "")
            != document_version_hash,
        )):
            return "PREPARED_PROPOSITION_PROTOCOL_INVALID"
        coverage_by_span_id = {
            str(item.get("source_span_id") or ""): item
            for item in proposition_artifact.get("coverage_manifest", [])
            if isinstance(item, Mapping) and str(item.get("source_span_id") or "")
        }
        covered_span_ids = set(coverage_by_span_id)
        expected_span_ids = {
            str(span.get("source_span_id") or "") for span in source_spans
        }
        if covered_span_ids != expected_span_ids:
            return "PREPARED_PROPOSITION_COVERAGE_INVALID"
        if any(
            str(coverage_by_span_id[span_id].get("source_span_cache_key") or "")
            != _source_span_cache_key(
                span,
                document_version_hash=document_version_hash,
            )
            for span_id, span in {
                str(item.get("source_span_id") or ""): item
                for item in source_spans
            }.items()
        ):
            return "PREPARED_PROPOSITION_SOURCE_CACHE_INVALID"
    alignment_artifacts = prepared_evidence_artifact.get(
        "contract_alignment_artifacts"
    )
    if alignment_artifacts is not None and not isinstance(
        alignment_artifacts, Mapping
    ):
        return "PREPARED_CONTRACT_ALIGNMENT_SET_INVALID"
    for alignment in dict(alignment_artifacts or {}).values():
        if not isinstance(alignment, Mapping) or str(
            alignment.get("schema_version") or ""
        ) != CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION:
            return "PREPARED_CONTRACT_ALIGNMENT_PROTOCOL_INVALID"
    return ""


def _fulltext_structuring_state(
    *,
    eligibility: Mapping[str, Any],
    use_llm: bool,
    llm_retry: Mapping[str, Any] | None,
    deterministic_complete: bool,
) -> dict[str, Any]:
    """Build the durable state that protects evidence-gate accounting."""

    decision = dict(eligibility or {})
    retry = dict(llm_retry or {})
    eligible = bool(decision.get("eligible"))
    role = str(decision.get("role") or "")
    reason = str(decision.get("reason") or "")
    if not eligible:
        if role == "duplicate_reuse_skip":
            status = "not_required_duplicate_reuse"
        elif role == "metadata_only":
            status = "metadata_only_no_fulltext"
        elif role == "alignment_not_executed":
            status = "alignment_not_executed"
        else:
            status = "not_required_deterministic_reject"
        return {
            "schema_version": "fulltext_structuring_v1",
            "status": status,
            "eligible_for_evidence_admission": False,
            "reason": reason,
            "role": role,
            "alignment_status": "NOT_EXECUTED" if role == "alignment_not_executed" else "REJECTED",
            "llm_attempted": False,
            "llm_error": "",
        }
    if deterministic_complete:
        return {
            "schema_version": "fulltext_structuring_v1",
            "status": "structured_deterministic",
            "eligible_for_evidence_admission": True,
            "reason": "deterministic_papergraph_structure_satisfies_required_fields",
            "role": role,
            "llm_attempted": False,
            "llm_error": "",
        }
    if retry.get("succeeded"):
        return {
            "schema_version": "fulltext_structuring_v1",
            "status": "structured_by_llm",
            "eligible_for_evidence_admission": True,
            "reason": "llm_structure_completed_after_deterministic_fulltext_admission",
            "role": role,
            "llm_attempted": True,
            "llm_error": "",
            "extractor": str(retry.get("extractor") or ""),
        }
    return {
        "schema_version": "fulltext_structuring_v1",
        "status": "metadata_plus_fulltext_pending_structuring",
        "eligible_for_evidence_admission": False,
        "reason": (
            "llm_structuring_not_requested_or_unavailable_after_deterministic_fulltext_admission"
            if not use_llm
            else "llm_structuring_failed_after_deterministic_fulltext_admission"
        ),
        "role": role,
        "llm_attempted": bool(retry.get("attempted")),
        "llm_error": str(retry.get("error") or ""),
    }


def select_zhizhi_import_results(
    results: list[dict[str, Any]],
    import_top_k: int,
    layer_minimums: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from ._literature_scoring import zhizhi_import_candidate_key, zhizhi_import_minimum_plan, zhizhi_import_priority_score
        from ._models import ZHIZHI_IMPORT_LAYER_LABELS, ZHIZHI_IMPORT_LAYER_PRIORITY
        from ._utils import clamp_int
    except ImportError:
        from _literature_scoring import zhizhi_import_candidate_key, zhizhi_import_minimum_plan, zhizhi_import_priority_score
        from _models import ZHIZHI_IMPORT_LAYER_LABELS, ZHIZHI_IMPORT_LAYER_PRIORITY
        from _utils import clamp_int
    limit = clamp_int(import_top_k, 1, SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K)
    candidates = [dict(item) for item in results if isinstance(item, dict)]
    candidate_counts = Counter(str(item.get("stratified_layer") or "unlayered") for item in candidates)
    evidence_lane_priority = (
        "TYPE_DIRECTED_PRIMARY_SOURCE_EVIDENCE",
        "TYPE_DIRECTED_COMPONENT_BRIDGE_EVIDENCE",
        "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE",
        "ADVERSE_OR_REVERSAL_EVIDENCE",
        "BOUNDARY_OR_NEGATIVE_EVIDENCE",
        "FOUNDATIONAL_BRIDGE",
        "BACKGROUND_REVIEW",
    )

    def evidence_lane(candidate: dict[str, Any]) -> str:
        assessment = (
            candidate.get("alignment_assessment")
            if isinstance(candidate.get("alignment_assessment"), dict)
            else {}
        )
        type_evidence = (
            assessment.get("type_directed_evidence")
            if isinstance(assessment.get("type_directed_evidence"), dict)
            else {}
        )
        return str(
            candidate.get("evidence_lane")
            or assessment.get("evidence_lane")
            or type_evidence.get("evidence_lane")
            or ""
        )

    def portfolio_roles(candidate: dict[str, Any]) -> set[str]:
        assessment = (
            candidate.get("alignment_assessment")
            if isinstance(candidate.get("alignment_assessment"), dict)
            else {}
        )
        lane = evidence_lane(candidate)
        layer = str(candidate.get("stratified_layer") or "")
        role_text = " ".join(
            str(value or "")
            for value in (
                candidate.get("evidence_role"),
                candidate.get("evidence_path_role"),
                candidate.get("evidence_kind"),
                candidate.get("target_lane"),
                candidate.get("evidence_path_polarity"),
                candidate.get("research_role"),
                assessment.get("evidence_role"),
                assessment.get("evidence_path_role"),
                assessment.get("evidence_kind"),
                assessment.get("evidence_polarity"),
                lane,
            )
        ).lower()
        roles: set[str] = set()
        polarity = str(
            candidate.get("evidence_polarity")
            or candidate.get("evidence_path_polarity")
            or assessment.get("evidence_polarity")
            or assessment.get("evidence_path_polarity")
            or ""
        ).lower()
        supports_primary_claim = assessment.get("supports_primary_claim")
        if (
            assessment.get("core_eligible") is True
            or lane == "TYPE_DIRECTED_PRIMARY_SOURCE_EVIDENCE"
        ) and (
            supports_primary_claim is True
            or (
                supports_primary_claim is not False
                and polarity not in {"opposing", "boundary"}
            )
        ):
            roles.add("direct_contract_core")
        if any(
            marker in role_text
            for marker in (
                "component",
                "bridge",
                "type_directed_component_bridge",
            )
        ) or lane == "TYPE_DIRECTED_COMPONENT_BRIDGE_EVIDENCE":
            roles.add("component_or_bridge")
        if any(
            marker in role_text
            for marker in ("boundary", "generalization", "negative_evidence")
        ):
            roles.add("boundary_or_negative")
        if any(
            marker in role_text
            for marker in ("adverse", "reversal", "opposing")
        ):
            roles.add("adverse_or_reversal")
        if (
            layer == "L0_review"
            or any(
                marker in role_text
                for marker in ("background", "framework", "context_review")
            )
        ):
            roles.add("background_or_framework")
        if (
            layer == "L1_milestone"
            or any(
                marker in role_text
                for marker in (
                    "method",
                    "platform",
                    "foundation",
                    "benchmark",
                    "calibration",
                )
            )
        ):
            roles.add("method_or_foundation")
        return roles

    candidate_lane_counts = Counter(
        evidence_lane(item) or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
        for item in candidates
    )

    def lane_diverse_order(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Round-robin source-bound evidence roles, ranking within each role."""
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in pool:
            grouped[evidence_lane(item) or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"].append(item)
        def full_text_discovery_signal(candidate: dict[str, Any]) -> int:
            payload = candidate.get("papergraph_input") if isinstance(candidate.get("papergraph_input"), dict) else {}
            return int(bool(
                candidate.get("open_access_pdf")
                or candidate.get("full_text_url")
                or candidate.get("pmc_id")
                or payload.get("open_access_pdf")
                or str(payload.get("full_text_excerpt") or "").strip()
            ))

        for items in grouped.values():
            items.sort(
                key=lambda candidate: (
                    full_text_discovery_signal(candidate),
                    zhizhi_import_priority_score(candidate),
                ),
                reverse=True,
            )
        ordered: list[dict[str, Any]] = []
        lane_order = [
            lane
            for lane in evidence_lane_priority
            if grouped.get(lane)
        ]
        if grouped.get("PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"):
            lane_order.append("PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE")
        while lane_order:
            next_round: list[str] = []
            for lane in lane_order:
                items = grouped.get(lane) or []
                if not items:
                    continue
                ordered.append(items.pop(0))
                if items:
                    next_round.append(lane)
            lane_order = next_round
        return ordered
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    default_plan = zhizhi_import_minimum_plan(limit)
    if isinstance(layer_minimums, dict):
        min_plan = {
            layer: max(0, int(layer_minimums.get(layer, 0) or 0))
            for layer in ZHIZHI_IMPORT_LAYER_PRIORITY
        }
        remaining = max(0, limit - sum(min_plan.values()))
        if remaining:
            min_plan["L4_regular"] = min_plan.get("L4_regular", 0) + remaining
    else:
        min_plan = default_plan

    def add_candidate(candidate: dict[str, Any], reason: str) -> bool:
        key = zhizhi_import_candidate_key(candidate)
        if key in selected_keys or len(selected) >= limit:
            return False
        item = dict(candidate)
        item["zhizhi_import_reason"] = reason
        lane = evidence_lane(item)
        if lane:
            item["evidence_lane"] = lane
        selected.append(item)
        selected_keys.add(key)
        return True

    portfolio_minimums = (
        {
            "direct_contract_core": 2,
            "component_or_bridge": 1,
            "boundary_or_negative": 1,
            "adverse_or_reversal": 1,
            "background_or_framework": 1,
            "method_or_foundation": 1,
        }
        if limit >= 20
        else {}
    )
    candidate_portfolio_counts = Counter(
        role for item in candidates for role in portfolio_roles(item)
    )
    for role, needed in portfolio_minimums.items():
        selected_role_count = sum(
            role in portfolio_roles(item) for item in selected
        )
        if selected_role_count >= needed:
            continue
        role_candidates = sorted(
            [item for item in candidates if role in portfolio_roles(item)],
            key=zhizhi_import_priority_score,
            reverse=True,
        )
        for candidate in role_candidates:
            if add_candidate(candidate, f"evidence_portfolio_minimum:{role}"):
                selected_role_count += 1
            if selected_role_count >= needed or len(selected) >= limit:
                break

    for layer in ZHIZHI_IMPORT_LAYER_PRIORITY:
        needed = min_plan.get(layer, 0)
        if needed <= 0:
            continue
        layer_candidates = lane_diverse_order(
            [item for item in candidates if str(item.get("stratified_layer") or "") == layer]
        )
        picked = 0
        for candidate in layer_candidates:
            if add_candidate(candidate, f"layer_minimum:{layer}"):
                picked += 1
            if picked >= needed:
                break

    # Once layer floors are represented, reserve one slot for every available
    # type-directed evidence lane before ordinary score backfill.  This avoids
    # overfitting the import unit to one easily retrieved evidence role.
    selected_lane_counts = Counter(evidence_lane(item) for item in selected if evidence_lane(item))
    for lane in evidence_lane_priority:
        if len(selected) >= limit:
            break
        if candidate_lane_counts.get(lane, 0) <= 0 or selected_lane_counts.get(lane, 0) > 0:
            continue
        lane_candidates = sorted(
            [item for item in candidates if evidence_lane(item) == lane],
            key=zhizhi_import_priority_score,
            reverse=True,
        )
        for candidate in lane_candidates:
            if add_candidate(candidate, f"evidence_lane_minimum:{lane}"):
                selected_lane_counts[lane] += 1
                break

    remaining = sorted(
        candidates,
        key=lambda item: (
            -selected_lane_counts.get(evidence_lane(item), 0),
            zhizhi_import_priority_score(item),
        ),
        reverse=True,
    )
    for candidate in remaining:
        if len(selected) >= limit:
            break
        add_candidate(candidate, "score_backfill")

    selected_counts = Counter(str(item.get("stratified_layer") or "unlayered") for item in selected)
    selected_lane_counts = Counter(
        evidence_lane(item) or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
        for item in selected
    )
    selected_portfolio_counts = Counter(
        role for item in selected for role in portfolio_roles(item)
    )
    missing_portfolio_roles = [
        {
            "role": role,
            "target": target,
            "selected": int(selected_portfolio_counts.get(role) or 0),
            "candidates": int(candidate_portfolio_counts.get(role) or 0),
        }
        for role, target in portfolio_minimums.items()
        if int(selected_portfolio_counts.get(role) or 0) < target
    ]
    missing_layers = [
        {
            "layer": layer,
            "label": ZHIZHI_IMPORT_LAYER_LABELS.get(layer, layer),
            "target": target,
            "selected": selected_counts.get(layer, 0),
            "candidates": candidate_counts.get(layer, 0),
        }
        for layer, target in min_plan.items()
        if selected_counts.get(layer, 0) < target
    ]
    report = {
        "strategy": (
            "evidence_portfolio_then_layer_minimum_then_evidence_lane_then_"
            "score_backfill"
            if portfolio_minimums
            else "layer_minimum_then_evidence_lane_then_score_backfill"
        ),
        "custom_layer_minimums": bool(layer_minimums),
        "requested_import_top_k": import_top_k,
        "effective_import_top_k": limit,
        "min_per_layer": min_plan,
        "candidate_counts_by_layer": dict(candidate_counts),
        "selected_counts_by_layer": dict(selected_counts),
        "candidate_counts_by_evidence_lane": dict(candidate_lane_counts),
        "selected_counts_by_evidence_lane": dict(selected_lane_counts),
        "evidence_portfolio_minimums": portfolio_minimums,
        "candidate_counts_by_evidence_portfolio_role": dict(
            candidate_portfolio_counts
        ),
        "selected_counts_by_evidence_portfolio_role": dict(
            selected_portfolio_counts
        ),
        "missing_evidence_portfolio_roles": missing_portfolio_roles,
        "missing_layers": missing_layers,
        "selected_result_indexes": [item.get("result_index") for item in selected],
    }
    return selected, report

def import_literature_text(
    project_id: str,
    title: str = "",
    citation: str = "",
    text: str = "",
    provider: str = "manual",
    source_type: str = "abstract",
    url: str = "",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    openalex_id: str = "",
    authors: list[str] | None = None,
    year: str = "",
    venue: str = "",
    use_llm: bool | None = None,
    extraction_quality: dict[str, Any] | None = None,
    full_text_enrichment: dict[str, Any] | None = None,
    sub_hypothesis: str = "",
) -> str:
    try:
        from ._project import load_project
        from ._science_execution_policy import resolve_science_execution_policy
        from ._utils import first_sentences, trim_text
    except ImportError:
        from _project import load_project
        from _science_execution_policy import resolve_science_execution_policy
        from _utils import first_sentences, trim_text
    project = load_project(project_id)
    execution_policy = resolve_science_execution_policy(project, use_llm=use_llm)
    use_llm = execution_policy.use_llm
    parsed = extract_paper_structure(text, use_llm=use_llm)
    inferred_title = title or parsed.get("title") or first_sentences(text, 1) or "Untitled paper"
    inferred_doi = _first_optional_identifier(doi, parsed.get("doi", ""))
    inferred_arxiv_id = _first_optional_identifier(arxiv_id, parsed.get("arxiv_id", ""))
    inferred_authors = authors or parsed.get("authors", [])
    inferred_year = year or parsed.get("year", "")
    inferred_venue = venue or parsed.get("venue", "")
    inferred_citation = citation or parsed.get("citation") or build_citation(
        title=inferred_title,
        authors=inferred_authors,
        year=inferred_year,
        doi=inferred_doi,
        arxiv_id=inferred_arxiv_id,
    )
    full_text_excerpt = trim_text(text, 120_000) if source_type in {
            "file", "pdf", "pdf_ocr_pending", "full_text", "manual_file",
            "docx_supplement", "xlsx_supplement", "html_full_text", "epub_reference",
        } or len(text) > 2500 else ""
    sub_id = str(sub_hypothesis).strip()
    alignment_contract = next(
        (
            item.get("research_question_contract")
            for item in project.get("sub_hypotheses", [])
            if isinstance(item, Mapping)
            and str(item.get("id") or item.get("sub_hypothesis_id") or "") == sub_id
            and isinstance(item.get("research_question_contract"), Mapping)
        ),
        None,
    )
    commit_kwargs = {
        "project_id": project_id,
        "title": inferred_title,
        "citation": inferred_citation,
        "use_llm": use_llm,
        "authors": inferred_authors,
        "year": inferred_year,
        "venue": inferred_venue,
        "provider": provider,
        "source_type": source_type,
        "doi": inferred_doi,
        "arxiv_id": inferred_arxiv_id,
        "semantic_scholar_id": semantic_scholar_id,
        "openalex_id": openalex_id,
        "url": url,
        "abstract": parsed["abstract"],
        "conclusion": parsed["conclusion"],
        "strengths": parsed["strengths"],
        "improvements": parsed["improvements"],
        "method": parsed["method"],
        "scenario": parsed["scenario"],
        "benchmark": parsed["benchmark"],
        "contribution": parsed["contribution"],
        "limitation": parsed["limitation"],
        "full_text_excerpt": full_text_excerpt,
        "extraction_quality": extraction_quality,
        "full_text_enrichment": full_text_enrichment,
        "gap_signals": (
            parsed.get("gap_signals")
            if isinstance(parsed.get("gap_signals"), list) else None
        ),
        "causal_chains": (
            parsed.get("causal_chains")
            if isinstance(parsed.get("causal_chains"), list) else None
        ),
        "import_context": {"sub_hypothesis_id": sub_id} if sub_id else None,
    }
    paper_id = _prepared_paper_id(commit_kwargs, None)
    prepared_evidence_artifact = _prepare_document_evidence_artifact(
        project=project,
        commit_kwargs=commit_kwargs,
        paper_id=paper_id,
        policy=execution_policy,
        alignment_contract=(
            alignment_contract if isinstance(alignment_contract, Mapping) else None
        ),
        existing_record=None,
        preparation_decision=document_proposition_preparation_decision(
            acquired_full_text=bool(full_text_excerpt),
            research_role="PENDING",
            classification_status="CLASSIFICATION_PENDING",
            contract_bound=isinstance(alignment_contract, Mapping),
        ),
    )
    if isinstance(prepared_evidence_artifact.get("subhypothesis_bindings"), list):
        commit_kwargs["subhypothesis_bindings"] = [
            dict(item)
            for item in prepared_evidence_artifact["subhypothesis_bindings"]
            if isinstance(item, Mapping)
        ]
    commit_kwargs["prepared_paper_id"] = paper_id
    commit_kwargs["document_descriptor"] = dict(
        prepared_evidence_artifact.get("document_descriptor") or {}
    )
    commit_kwargs["prepared_evidence_artifact"] = prepared_evidence_artifact
    committed = commit_prepared_literature_candidate(
        {
            "status": "prepared",
            "schema_version": "prepared_evidence_candidate_v3",
            "project_id": project_id,
            "base_state_version": int(project.get("state_version") or 0),
            "commit_kwargs": commit_kwargs,
        },
        project=project,
        identity_index=build_project_paper_identity_index(project),
        save=True,
    )
    return json.dumps(committed, ensure_ascii=False, indent=2)

def import_literature_file(
    project_id: str,
    path: str,
    title: str = "",
    citation: str = "",
    provider: str = "manual_file",
    source_type: str = "file",
    use_llm: bool | None = None,
    sub_hypothesis: str = "",
) -> str:
    try:
        from ._document_conversion import convert_literature_document
        from ._pdf_extraction import extract_pdf_content
        from ._utils import read_literature_file, safe_workspace_path
    except ImportError:
        from _document_conversion import convert_literature_document
        from _pdf_extraction import extract_pdf_content
        from _utils import read_literature_file, safe_workspace_path
    target = safe_workspace_path(path)
    inferred_title = title or target.stem.replace("_", " ")
    inferred_citation = citation or inferred_title
    extraction_quality: dict[str, Any] | None = None
    full_text_enrichment: dict[str, Any] | None = None
    effective_source_type = source_type
    if target.suffix.lower() == ".pdf":
        extracted = extract_pdf_content(
            target,
            {"title": inferred_title, "citation": inferred_citation, "source_path": str(target)},
            sub_hypothesis or None,
        )
        text = str(extracted["text"])
        full_text_enrichment = dict(extracted["report"])
        full_text_enrichment["source_path"] = str(target)
        extraction_quality = {
            "pdf_extraction_summary": extraction_report_summary(full_text_enrichment),
            "needs_supplement": bool((full_text_enrichment.get("validation") or {}).get("needs_supplement")),
            "document_conversion": full_text_enrichment.get("document_conversion_run", {}),
            "requires_human_review": bool(
                (full_text_enrichment.get("evidence_admission") or {}).get("requires_human_review")
            ),
        }
        admission = full_text_enrichment.get("evidence_admission") if isinstance(full_text_enrichment.get("evidence_admission"), dict) else {}
        ingestion_status = str(full_text_enrichment.get("ingestion_status") or "")
        candidate_only = bool(admission.get("candidate_only")) or ingestion_status in {"NEEDS_OCR", "DOCUMENT_INGESTION_FAILED", "TEXT_INTEGRITY_FAILED", "SECTION_STRUCTURE_PENDING", "SOURCE_LOCATORS_INCOMPLETE"}
        effective_source_type = "pdf_ocr_pending" if candidate_only else "pdf"
    else:
        if target.suffix.lower() in {".docx", ".xlsx", ".html", ".htm", ".epub"}:
            converted = convert_literature_document(target)
            text = converted.markdown
            full_text_enrichment = dict(converted.report)
            full_text_enrichment["source_path"] = str(target)
            extraction_quality = {
                "document_conversion": extraction_report_summary(full_text_enrichment),
                "requires_human_review": bool(
                    (full_text_enrichment.get("evidence_admission") or {}).get("requires_human_review")
                ),
            }
            effective_source_type = converted.capability.default_source_type
        else:
            text = read_literature_file(target)
    return import_literature_text(
        project_id=project_id,
        title=inferred_title,
        citation=inferred_citation,
        text=text,
        provider=provider,
        source_type=effective_source_type,
        use_llm=use_llm,
        extraction_quality=extraction_quality,
        full_text_enrichment=full_text_enrichment,
        sub_hypothesis=sub_hypothesis,
    )

def prepare_literature_candidate(
    project_id: str,
    search_id: str,
    result_index: int = 0,
    use_llm: bool | None = None,
    enable_focal_variable_synonym_dictionary: bool | None = None,
    stratified_layer_override: str = "",
    query_branch_override: str = "",
    alignment_contract: dict[str, Any] | None = None,
    alignment_contracts: list[dict[str, Any]] | None = None,
    evidence_kind_override: str = "",
    foundational_bridge_assessment: dict[str, Any] | None = None,
    force_import: bool = False,
    *,
    project: dict[str, Any] | None = None,
    search_record: dict[str, Any] | None = None,
    identity_index: Mapping[str, dict[str, Any]] | None = None,
    single_flight: LiteraturePreparationSingleFlight | None = None,
    alignment_memo: dict[str, dict[str, Any]] | None = None,
    include_full_text: bool = True,
) -> dict[str, Any]:
    try:
        from ._literature_scoring import domain_relevance_assessment, publication_quality_assessment, should_reject_for_domain
        from ._literature_search import (
            _v3_slot_candidate_scope_assessment,
            enrich_papergraph_payload,
            is_retracted_literature_result,
        )
        from ._project import load_project, load_search, project_research_domain_context
        from ._research_alignment import (
            evidence_kind_from_branch,
        )
        from ._paper_classification import assess_paper_domain, classify_paper_content
        from ._retrieval_strategy import classify_paper_research_role
        from ._science_execution_policy import resolve_science_execution_policy
        from ._utils import trim_text
    except ImportError:
        from _literature_scoring import domain_relevance_assessment, publication_quality_assessment, should_reject_for_domain
        from _literature_search import (
            _v3_slot_candidate_scope_assessment,
            enrich_papergraph_payload,
            is_retracted_literature_result,
        )
        from _project import load_project, load_search, project_research_domain_context
        from _research_alignment import (
            evidence_kind_from_branch,
        )
        from _paper_classification import assess_paper_domain, classify_paper_content
        from _retrieval_strategy import classify_paper_research_role
        from _science_execution_policy import resolve_science_execution_policy
        from _utils import trim_text
    project = project if isinstance(project, dict) else load_project(project_id)
    execution_policy = resolve_science_execution_policy(project, use_llm=use_llm)
    use_llm = execution_policy.use_llm
    synonym_dictionary_enabled = (
        bool(use_llm)
        if enable_focal_variable_synonym_dictionary is None
        else bool(enable_focal_variable_synonym_dictionary)
    )
    search_record = (
        search_record if isinstance(search_record, dict) else load_search(search_id)
    )
    scope_admission = _decomposed_project_search_scope_admission(
        project,
        project_id,
        search_record,
    )
    if not scope_admission.get("allowed"):
        log_event(
            "SCIENCE",
            "import_blocked_unscoped_decomposed_project_search",
            project_id=project_id,
            search_id=search_id,
            scope_kind=scope_admission.get("kind"),
        )
        return {
            "status": "terminal",
            "response": {
                "status": "BLOCKED_SUBHYPOTHESIS_RETRIEVAL_REQUIRED",
                "terminal": False,
                "project_id": project_id,
                "search_id": search_id,
                "reason_code": scope_admission.get("reason_code"),
                "retrieval_scope": scope_admission.get("scope"),
                "allowed_next_stages": ["run_zhizhi_subhypothesis_analysis"],
            },
        }
    retrieval_scope = dict(scope_admission.get("scope") or {})
    ad_hoc_discovery = scope_admission.get("kind") == "ad_hoc_discovery"
    results = [
        item
        for item in (
            list(search_record.get("results") or [])
            + list(search_record.get("aligned_reserve_results") or [])
        )
        if isinstance(item, dict)
    ]
    if not results:
        raise ValueError(
            f"Search {search_id} has no retrieved papers. Do not invent a substitute; retry search or import user-provided text."
        )
    try:
        index = int(result_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid result_index: {result_index}") from exc
    result_match = next(
        (
            item
            for item in results
            if int(item.get("result_index") or 0) == index
        ),
        None,
    )
    if result_match is None and 0 <= index < len(results):
        # Compatibility for older search records whose results predate the
        # explicit stable result_index field.
        result_match = results[index]
    if result_match is None:
        raise ValueError(
            f"result_index {index} out of range for search {search_id}; "
            f"selected_and_aligned_reserve_results={len(results)}"
        )
    result = dict(result_match)
    if is_retracted_literature_result(result):
        log_event(
            "SCIENCE",
            "import_rejected_retracted_article",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            title=trim_text(str(result.get("title") or ""), 180),
            reason="title_contains_RETRACTED_ARTICLE",
        )
        return {
            "status": "terminal",
            "response": {
                "status": "rejected_retracted_article",
                "reason": "title_contains_RETRACTED_ARTICLE",
                "search_id": search_id,
                "result_index": index,
            },
        }
    if stratified_layer_override:
        result["stratified_layer"] = str(stratified_layer_override)
    if query_branch_override:
        result["query_branch"] = str(query_branch_override)
    task_provenance = (
        dict(search_record.get("research_question_task_provenance"))
        if isinstance(search_record.get("research_question_task_provenance"), dict)
        else {}
    )
    research_question_task_id = str(
        result.get("research_question_task_id")
        or task_provenance.get("research_question_task_id")
        or ""
    ).strip()
    evidence_slot = str(
        result.get("evidence_slot") or task_provenance.get("evidence_slot") or ""
    ).strip()
    plan_revision = str(
        result.get("plan_revision") or task_provenance.get("plan_revision") or ""
    ).strip()
    query_provenance = {
        field: (
            result.get(field)
            or task_provenance.get(field)
            or ""
        )
        for field in (
            "groupchat_id",
            "run_id",
            "retrieval_wave_id",
            "sub_hypothesis_id",
            "research_question_contract_id",
            "research_question_contract_hash",
            "query_branch_id",
            "query_branch_role",
        )
    }
    bridge_assessment = (
        dict(foundational_bridge_assessment)
        if isinstance(foundational_bridge_assessment, dict)
        else {}
    )
    bridge_requested = bool(bridge_assessment)
    bridge_approved = bool(
        bridge_assessment.get("bridge_eligible")
        and str(bridge_assessment.get("project_id") or "") == project_id
    )
    if bridge_approved and isinstance(alignment_contract, dict) and alignment_contract:
        bridge_approved = (
            str(bridge_assessment.get("alignment_contract_hash") or "")
            == str(alignment_contract.get("contract_hash") or "")
        )
    if bridge_approved:
        result["research_role"] = "FOUNDATIONAL_MECHANISM_BRIDGE"
        result["foundational_bridge_assessment"] = bridge_assessment
    elif ad_hoc_discovery:
        # Background mapping may be useful, but cannot be upgraded into a
        # causal-edge or CORE record merely because it passed a broad domain
        # gate.  The persisted scope enforces this across later stages.
        result["research_role"] = "BACKGROUND"
    requested_evidence_kind = str(
        evidence_kind_override
        or ("foundational_mechanism_bridge" if bridge_approved else "")
        or evidence_kind_from_branch(str(result.get("query_branch") or ""))
    )
    alignment_assessment: dict[str, Any] = {}
    alignment_override: dict[str, Any] = {}
    targeted_alignment_admission = (
        result.get("targeted_alignment_admission")
        if isinstance(result.get("targeted_alignment_admission"), dict)
        else {}
    )
    prefulltext_pending_from_search = bool(
        (
            result.get("pending_full_text_verification")
            or str(result.get("targeted_admission_tier") or targeted_alignment_admission.get("admission_tier") or "")
            == "AUXILIARY_PENDING_FULLTEXT"
            or result.get("prefulltext_import_eligible")
        )
        and (
            targeted_alignment_admission.get("prefulltext_import_eligible") is True
            or result.get("prefulltext_import_eligible") is True
        )
    )
    v3_slot_scope, v3_slot_scope_error = _v3_slot_candidate_scope_from_search(
        search_record,
        result,
        alignment_contract,
        retrieval_scope,
    )
    v3_foundation_contract, v3_foundation_error = _v3_foundational_context_from_search(
        search_record,
        result,
        alignment_contract,
        retrieval_scope,
    )
    v3_contract_import = bool(v3_slot_scope or v3_slot_scope_error)
    if (v3_contract_import and v3_slot_scope_error) or v3_foundation_error:
        reason_code = v3_slot_scope_error or v3_foundation_error
        log_event(
            "SCIENCE",
            "import_rejected_v3_slot_scope_provenance",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            sub_hypothesis_id=str(
                result.get("sub_hypothesis_id")
                or retrieval_scope.get("sub_hypothesis_id")
                or ""
            ),
            evidence_slot=str(result.get("evidence_slot") or ""),
            reason_code=reason_code,
        )
        return {
            "status": "terminal",
            "response": {
                "status": "rejected_v3_slot_scope_provenance",
                "reason_code": reason_code,
                "search_id": search_id,
                "result_index": index,
            },
        }
    if v3_slot_scope:
        # Search already performed this task-local metadata gate.  Recompute
        # only from the persisted task scope so a restart cannot drift into
        # historical project-context/object/causal-edge admission.
        scope_assessment = _v3_slot_candidate_scope_assessment(result, v3_slot_scope)
        alignment_assessment = _v3_slot_scope_alignment_assessment(
            scope_assessment,
            alignment_contract,
            assessment_stage="v3_slot_metadata_import",
        )
        requested_evidence_kind = requested_evidence_kind or "v3_slot_candidate"
        result["alignment_assessment"] = alignment_assessment
        prefulltext_pending_from_search = bool(scope_assessment.get("passes"))
        alignment_override = {
            "v3_slot_candidate_pending_fulltext": bool(scope_assessment.get("passes")),
            "direct_target_evidence": False,
            "reason": (
                "V3 task-local metadata scope admitted this candidate for full-text "
                "verification; source-span, assertion, and typed-slot gates remain pending."
            ),
        }
    elif v3_foundation_contract:
        alignment_assessment = _v3_foundational_context_alignment_assessment(
            result,
            v3_foundation_contract,
            alignment_contract,
            assessment_stage="v3_foundational_context_metadata_import",
        )
        requested_evidence_kind = "foundational_context"
        result["alignment_assessment"] = alignment_assessment
        prefulltext_pending_from_search = bool(alignment_assessment.get("passes"))
        alignment_override = {
            "v3_foundational_context_pending_fulltext": bool(
                alignment_assessment.get("passes")
            ),
            "direct_target_evidence": False,
            "reason": (
                "V3 foundational context is rationale-only and remains pending "
                "source-bound assertion admission."
            ),
        }
    elif isinstance(alignment_contract, dict) and alignment_contract:
        # A declared V3 contract is valid only with its persisted task scope.
        # Do not reinterpret it through project-context, object, or causal-edge
        # alignment rules when provenance is incomplete.
        log_event(
            "SCIENCE",
            "import_rejected_v3_scope_required",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            sub_hypothesis_id=str(
                result.get("sub_hypothesis_id")
                or retrieval_scope.get("sub_hypothesis_id")
                or ""
            ),
            evidence_slot=str(result.get("evidence_slot") or ""),
        )
        return {
            "status": "terminal",
            "response": {
                "status": "rejected_v3_scope_required",
                "reason_code": "V3_RETRIEVAL_SCOPE_REQUIRED",
                "search_id": search_id,
                "result_index": index,
            },
        }
    project_domain = str(project.get("domain") or search_record.get("domain") or "")
    project_domain_context = project_research_domain_context(project)
    # Preserve domain_relevance from search phase if already assessed
    existing_relevance = result.get("domain_relevance")
    if not isinstance(existing_relevance, dict) or not existing_relevance.get("score"):
        result["domain_relevance"] = domain_relevance_assessment(
            result,
            domain=project_domain_context,
            query=str(search_record.get("query") or ""),
        )
    rejected_by_domain_gate = should_reject_for_domain(
        result,
        domain=project_domain_context,
        query=str(search_record.get("query") or ""),
    )
    domain_gate = result.get("domain_gate") if isinstance(result.get("domain_gate"), dict) else {}
    domain_review = result.get("domain_review") if isinstance(result.get("domain_review"), dict) else {}
    domain_override: dict[str, Any] = {}
    if rejected_by_domain_gate and not bridge_approved and not force_import:
        log_event(
            "SCIENCE",
            "import_rejected_by_domain_gate",
            search_id=search_id,
            result_index=index,
            title=trim_text(str(result.get("title") or ""), 120),
            domain=project_domain,
            score=result.get("domain_relevance", {}).get("score"),
            verdict=domain_gate.get("verdict") or result.get("domain_relevance", {}).get("verdict"),
            primary_verdict=result.get("domain_relevance", {}).get("verdict"),
            gate_verdict=domain_gate.get("verdict"),
            rejecting_stage=domain_gate.get("rejecting_stage"),
            reason=domain_gate.get("reason"),
            review_verdict=domain_review.get("verdict"),
        )
        raise ValueError(
            "Search result rejected before import by final domain gate: "
            f"title={trim_text(str(result.get('title') or ''), 120)}, "
            f"domain={project_domain}, gate={json.dumps(domain_gate, ensure_ascii=False)}, "
            f"primary_assessment={json.dumps(result['domain_relevance'], ensure_ascii=False)}, "
            f"review={json.dumps(domain_review, ensure_ascii=False)}"
        )
    if rejected_by_domain_gate and bridge_approved:
        original_verdict = str(domain_gate.get("verdict") or "reject")
        domain_gate = {
            **domain_gate,
            "verdict": "bridge",
            "original_verdict": original_verdict,
            "reason": "Historical mechanism bridge was qualified against its input--mediator--outcome contract; it remains rationale-only outside the direct target domain.",
        }
        result["domain_gate"] = domain_gate
        domain_override = {
            "foundational_mechanism_bridge": True,
            "original_gate_verdict": original_verdict,
            "direct_target_evidence": False,
        }
        log_event(
            "SCIENCE",
            "foundational_mechanism_bridge_domain_bypass",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            title=trim_text(str(result.get("title") or ""), 120),
            original_gate_verdict=original_verdict,
        )
    elif rejected_by_domain_gate and force_import:
        original_verdict = str(domain_gate.get("verdict") or "reject")
        domain_gate = {
            **domain_gate,
            "verdict": "override",
            "overridden_by_user": True,
            "original_verdict": original_verdict,
            "reason": "User explicitly forced import after reviewing the domain-gate rejection.",
        }
        result["domain_gate"] = domain_gate
        domain_override = {
            "force_import": True,
            "original_gate_verdict": original_verdict,
            "original_rejecting_stage": domain_gate.get("rejecting_stage"),
        }
        log_event(
            "SCIENCE",
            "import_forced_by_user",
            search_id=search_id,
            result_index=index,
            title=trim_text(str(result.get("title") or ""), 120),
            original_gate_verdict=original_verdict,
            original_rejecting_stage=domain_gate.get("rejecting_stage"),
        )
    payload = result.get("papergraph_input")
    if not isinstance(payload, dict):
        raise ValueError(f"Search result {index} has no papergraph_input")
    payload = dict(payload)
    quality = publication_quality_assessment(result)
    identity_candidate = {**result, **payload, "papergraph_input": payload}
    existing_project_record = find_project_paper_by_identity(
        identity_index,
        identity_candidate,
        project=project,
    )
    reused_project_full_text = bool(
        isinstance(existing_project_record, dict)
        and assess_full_text_acquisition(existing_project_record).get("full_text_available")
    )
    if reused_project_full_text:
        payload = _reuse_project_full_text_payload(payload, existing_project_record)
    initial_extraction_quality = extraction_quality_report(payload)
    enrichment_sources: list[str] = []
    batch_single_flight_reused = False

    needs_full_text_probe = bool(
        include_full_text and candidate_needs_full_text_probe(result, payload)
    )
    if reused_project_full_text:
        enrichment_sources = list(
            dict.fromkeys(
                [
                    *[
                        str(item)
                        for item in (existing_project_record.get("enrichment_sources") or [])
                        if str(item)
                    ],
                    "project_identity_full_text_reuse",
                ]
            )
        )
        log_event(
            "SCIENCE",
            "paper_full_text_reused_before_download",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            paper_id=str(existing_project_record.get("paper_id") or ""),
            sub_hypothesis_id=str(
                (alignment_contract or {}).get("sub_hypothesis_id")
                or (search_record.get("retrieval_scope") or {}).get("sub_hypothesis_id")
                or result.get("sub_hypothesis_id")
                or ""
            ),
            query_branch=str(query_branch_override or result.get("query_branch") or ""),
            research_question_task_id=research_question_task_id,
            evidence_slot=evidence_slot,
            plan_revision=plan_revision,
            identity_aliases=len(paper_identity_alias_keys(identity_candidate)),
            include_full_text=bool(include_full_text),
            acquisition_intent=(
                "scheduled_fulltext" if include_full_text else "metadata_only"
            ),
        )
    elif initial_extraction_quality.get("needs_enrichment") or needs_full_text_probe:
        def enrich_candidate() -> tuple[dict[str, Any], list[str]]:
            enrichment_result = dict(result)
            enrichment_result["_fulltext_extraction_context"] = {
                "alignment_contract_hash": str(
                    (alignment_contract or {}).get("contract_hash") or ""
                ),
                "sub_hypothesis_id": str(
                    (alignment_contract or {}).get("sub_hypothesis_id")
                    or (search_record.get("retrieval_scope") or {}).get("sub_hypothesis_id")
                    or result.get("sub_hypothesis_id")
                    or ""
                ),
                "retrieval_branch": str(
                    result.get("query_branch")
                    or result.get("retrieval_branch")
                    or ""
                ),
                # This context travels to the low-level PDF resolver.  It is
                # intentionally explicit because a bare URL-only extraction
                # event cannot tell whether a PDF was authorized for this
                # candidate, reused from cache, or found by another task.
                "project_id": project_id,
                "search_id": search_id,
                "result_index": index,
                "paper_identity": _alignment_memo_paper_key(identity_candidate),
                "research_question_task_id": research_question_task_id,
                "evidence_slot": evidence_slot,
                "plan_revision": plan_revision,
                "include_full_text": bool(include_full_text),
                "acquisition_intent": (
                    "scheduled_fulltext"
                    if include_full_text
                    else "metadata_only"
                ),
            }
            return enrich_papergraph_payload(
                payload,
                enrichment_result,
                include_full_text=bool(include_full_text),
            )

        if single_flight is not None:
            payload, enrichment_sources, single_flight_reused = single_flight.run(
                identity_candidate,
                enrich_candidate,
                # A metadata-only task must never inherit a full-text payload
                # from a concurrent owner of the same paper identity.  The
                # old shared scope made the completed payload, rather than
                # the caller's acquisition authorization, determine whether
                # PDF text appeared in the prepared record.
                flight_scope=(
                    f"{str((alignment_contract or {}).get('contract_hash') or 'generic')}:"
                    f"{'fulltext' if include_full_text else 'metadata_only'}"
                ),
            )
            if single_flight_reused:
                batch_single_flight_reused = True
                enrichment_sources = list(
                    dict.fromkeys([*enrichment_sources, "batch_single_flight_reuse"])
                )
                log_event(
                    "SCIENCE",
                    "paper_full_text_single_flight_reused",
                    project_id=project_id,
                    search_id=search_id,
                    result_index=index,
                    sub_hypothesis_id=str(
                        (alignment_contract or {}).get("sub_hypothesis_id")
                        or (search_record.get("retrieval_scope") or {}).get("sub_hypothesis_id")
                        or result.get("sub_hypothesis_id")
                        or ""
                    ),
                    query_branch=str(query_branch_override or result.get("query_branch") or ""),
                    research_question_task_id=research_question_task_id,
                    evidence_slot=evidence_slot,
                    plan_revision=plan_revision,
                )
        else:
            payload, enrichment_sources = enrich_candidate()
        if enrichment_sources:
            log_event(
                "SCIENCE",
                "paper_metadata_enriched",
                search_id=search_id,
                result_index=index,
                sub_hypothesis_id=str(
                    (alignment_contract or {}).get("sub_hypothesis_id")
                    or (search_record.get("retrieval_scope") or {}).get("sub_hypothesis_id")
                    or result.get("sub_hypothesis_id")
                    or ""
                ),
                query_branch=str(query_branch_override or result.get("query_branch") or ""),
                research_question_task_id=research_question_task_id,
                evidence_slot=evidence_slot,
                plan_revision=plan_revision,
                sources=",".join(enrichment_sources),
                include_full_text=bool(include_full_text),
                acquisition_intent=(
                    "scheduled_fulltext" if include_full_text else "metadata_only"
                ),
            )

    # Apply the metadata-only boundary after *all* acquisition paths,
    # including project-identity reuse. A background candidate may observe
    # that a canonical full text exists, but it must not attach that text to
    # this prepared result or change its admission accounting.
    if not include_full_text:
        suppressed_excerpt_chars = len(str(payload.get("full_text_excerpt") or ""))
        suppressed_pdf_url = str(payload.get("open_access_pdf") or "").strip()
        if suppressed_excerpt_chars or suppressed_pdf_url:
            payload = dict(payload)
            payload.pop("full_text_excerpt", None)
            payload.pop("open_access_pdf", None)
            payload.pop("open_access_source", None)
            payload.pop("full_text_report", None)
            payload.pop("_full_text_enrichment", None)
            enrichment_sources = list(dict.fromkeys([
                *enrichment_sources,
                "metadata_only_fulltext_suppressed",
            ]))
            log_event(
                "SCIENCE",
                "metadata_only_fulltext_suppressed",
                project_id=project_id,
                search_id=search_id,
                result_index=index,
                sub_hypothesis_id=str(
                    (alignment_contract or {}).get("sub_hypothesis_id") or ""
                ),
                excerpt_chars=suppressed_excerpt_chars,
                had_open_access_pdf=bool(suppressed_pdf_url),
                reason="metadata_only_preparation_never_attaches_fulltext",
            )

    post_enrichment_candidate = {
        **result,
        **payload,
        "papergraph_input": payload,
        "alignment_assessment": alignment_assessment or result.get("alignment_assessment", {}),
    }
    paper_for_classification = {
        **post_enrichment_candidate,
        "publication_types": list(
            payload.get("publication_types")
            or result.get("publication_types")
            or []
        ),
    }
    existing_domain_assessment = (
        result.get("paper_domain_assessment")
        if isinstance(result.get("paper_domain_assessment"), Mapping)
        and result.get("paper_domain_assessment", {}).get("status") == "CLASSIFIED"
        else None
    )
    paper_domain_assessment = (
        dict(existing_domain_assessment)
        if isinstance(existing_domain_assessment, Mapping)
        else assess_paper_domain(paper_for_classification, execution_policy)
    )
    paper_classification = classify_paper_content(
        paper_for_classification,
        execution_policy,
        domain_assessment=paper_domain_assessment,
        research_role=str(result.get("research_role") or "PENDING"),
        retrieval_layer=str(
            result.get("retrieval_layer")
            or result.get("stratified_layer")
            or ""
        ),
        admission_status="PENDING",
    )
    classified_candidate = {
        **post_enrichment_candidate,
        "paper_domain_assessment": dict(paper_domain_assessment),
        "paper_classification": dict(paper_classification),
    }
    question_card = (
        search_record.get("research_question_card")
        if isinstance(search_record.get("research_question_card"), Mapping)
        else {}
    )
    final_research_role_assessment = classify_paper_research_role(
        classified_candidate,
        dict(question_card),
        policy=execution_policy,
    ) if question_card else {
        "role": "PENDING",
        "allowed_use": "domain_pending",
        "reason": "Research-question card is unavailable for contract-bound role classification.",
        "reason_codes": ["RESEARCH_QUESTION_CARD_REQUIRED"],
    }
    final_research_role = str(
        final_research_role_assessment.get("role") or "PENDING"
    ).upper()
    paper_classification["research_role"] = final_research_role
    paper_classification["admission_status"] = (
        {
            "CORE_DIRECT": "CORE_CANDIDATE",
            "COMPONENT_SUPPORT": "AUXILIARY_CONTEXT",
            "BOUNDARY": "AUXILIARY_CONTEXT",
            "ADVERSE": "AUXILIARY_CONTEXT",
            "METHOD": "AUXILIARY_CONTEXT",
            "BACKGROUND": "AUXILIARY_CONTEXT",
            "OFF_TOPIC": "REJECTED",
        }.get(final_research_role, "PENDING")
        if paper_classification.get("status") == "CLASSIFIED"
        else "PENDING"
    )
    evidence_genre = str(paper_classification.get("evidence_genre") or "unknown")
    paper_genre_assessment = {
        "schema_version": "paper_genre_assessment_v2",
        "genre": evidence_genre,
        "evidence_genre": evidence_genre,
        "research_design": str(paper_classification.get("research_design") or "unknown"),
        "publication_form": str(paper_classification.get("publication_form") or "unknown"),
        "is_review": evidence_genre in {"systematic_review", "narrative_review", "contextual_synthesis"},
        "status": str(paper_classification.get("status") or "CLASSIFICATION_PENDING"),
        "reason_codes": list(paper_classification.get("reason_codes") or []),
        "source_anchors": list(paper_classification.get("source_anchors") or []),
    }
    post_fulltext_admission: dict[str, Any] = {
        "schema_version": "post_fulltext_admission_v1",
        "performed": False,
        "original_layer": str(result.get("stratified_layer") or "L4_regular"),
        "assigned_layer": str(result.get("stratified_layer") or "L4_regular"),
        "genre": str(paper_genre_assessment.get("genre") or "unclassified"),
        "is_review": bool(paper_genre_assessment.get("is_review")),
        "status": "METADATA_ONLY_NO_POST_FULLTEXT_RECLASSIFICATION",
        "foundation_revoked": False,
        "prefulltext_pending_verification": bool(prefulltext_pending_from_search),
    }
    acquired_full_text = len(str(payload.get("full_text_excerpt") or "").strip()) >= 500
    if (
        acquired_full_text
        and isinstance(alignment_contract, dict)
        and alignment_contract
    ):
        post_alignment_candidate = {
            **post_enrichment_candidate,
            "paper_genre": paper_genre_assessment,
        }
        if v3_slot_scope:
            post_alignment = _v3_slot_scope_alignment_assessment(
                _v3_slot_candidate_scope_assessment(
                    post_alignment_candidate,
                    v3_slot_scope,
                ),
                alignment_contract,
                assessment_stage="v3_slot_post_fulltext_scope",
            )
        elif v3_foundation_contract:
            post_alignment = _v3_foundational_context_alignment_assessment(
                post_alignment_candidate,
                v3_foundation_contract,
                alignment_contract,
                assessment_stage="v3_foundational_context_post_fulltext",
            )
        else:
            raise RuntimeError(
                "V3 post-fulltext import requires persisted slot or foundational "
                "context provenance; legacy causal alignment is not available."
            )
        alignment_assessment = post_alignment
        result["alignment_assessment"] = post_alignment
        assigned_kind = str(
            post_alignment.get("assigned_evidence_kind")
            or post_alignment.get("evidence_kind")
            or requested_evidence_kind
        )
        if assigned_kind:
            requested_evidence_kind = assigned_kind
        post_fulltext_admission.update(
            {
                "performed": True,
                "alignment_verdict": str(post_alignment.get("verdict") or ""),
                "alignment_import_eligible": bool(post_alignment.get("import_eligible")),
                "alignment_core_eligible": bool(post_alignment.get("core_eligible")),
                "corpus_admitted": bool(post_alignment.get("corpus_admitted")),
                "corpus_admission_reason": str(post_alignment.get("corpus_admission_reason") or ""),
                "evidence_role": str(post_alignment.get("evidence_role") or ""),
                "evidence_polarity": str(post_alignment.get("evidence_polarity") or ""),
                "gate_counting_evidence": bool(post_alignment.get("gate_counting_evidence")),
                "evidence_lane": str(post_alignment.get("evidence_lane") or ""),
                "status": "POST_FULLTEXT_ALIGNMENT_RETAINED",
            }
        )
        original_layer = str(post_fulltext_admission["original_layer"])
        if paper_genre_assessment.get("is_review"):
            if post_alignment.get("import_eligible"):
                result["stratified_layer"] = "L0_review"
                requested_evidence_kind = "background_review"
                post_fulltext_admission.update(
                    {
                        "assigned_layer": "L0_review",
                        "status": "POST_FULLTEXT_DEMOTED_TO_L0_REVIEW",
                        "requires_same_layer_backfill": False,
                    }
                )
            else:
                post_fulltext_admission.update(
                    {
                        "status": "POST_FULLTEXT_AUXILIARY_RESERVE",
                        "requires_same_layer_backfill": False,
                    }
                )
        elif not post_alignment.get("import_eligible"):
            post_project_background_only = bool(
                post_alignment.get("project_background_only")
                or post_alignment.get("excluded_from_sh_gap_synthesis")
                or str(post_alignment.get("sh_locality_scope") or "") == "project_background_only"
            )
            post_fulltext_admission.update(
                {
                    "status": (
                        "POST_FULLTEXT_CORPUS_NONCORE_RETAINED"
                        if post_alignment.get("corpus_admitted")
                        else "POST_FULLTEXT_AUXILIARY_RESERVE"
                    ),
                    "requires_same_layer_backfill": False,
                    "counts_toward_corpus_target": bool(
                        post_alignment.get("corpus_admitted")
                        and not post_project_background_only
                    ),
                    "counts_toward_gate": bool(
                        post_alignment.get("corpus_admitted")
                        and not post_project_background_only
                    ),
                    "project_background_only": post_project_background_only,
                    "excluded_from_sh_gap_synthesis": post_project_background_only,
                }
            )
        if bridge_requested and (
            paper_genre_assessment.get("is_review")
            or (
                not post_alignment.get("import_eligible")
                and not post_alignment.get("corpus_admitted")
            )
        ):
            bridge_approved = False
            bridge_assessment.update(
                {
                    "bridge_eligible": False,
                    "revoked_after_full_text": True,
                    "revocation_reason": (
                        "full-text genre is review/background"
                        if paper_genre_assessment.get("is_review")
                        else "full-text alignment no longer supports the foundation contract"
                    ),
                }
            )
            post_fulltext_admission["foundation_revoked"] = True
            post_fulltext_admission["requires_same_layer_backfill"] = True
        elif bridge_requested and bridge_approved and post_alignment.get("corpus_admitted"):
            bridge_assessment.update(
                {
                    "foundation_valid_after_fulltext": True,
                    "foundation_scope": bridge_assessment.get("foundation_scope")
                    or bridge_assessment.get("bridge_scope")
                    or "local_foundational_bridge",
                    "counts_toward_core": False,
                    "counts_toward_foundational_evidence": True,
                }
            )
            post_fulltext_admission.update(
                {
                    "status": "POST_FULLTEXT_FOUNDATIONAL_BRIDGE_RETAINED",
                    "foundation_valid_after_fulltext": True,
                    "counts_toward_gate": True,
                    "counts_toward_core": False,
                }
            )
        if post_fulltext_admission["status"] != "POST_FULLTEXT_ALIGNMENT_RETAINED":
            alignment_override = {
                **alignment_override,
                "post_fulltext_admission": dict(post_fulltext_admission),
                "direct_target_evidence": False,
            }

    # Full Markdown is already cached by enrich_papergraph_payload.  Keep the
    # expensive LLM step behind deterministic genre and contract admission so
    # rejected/background documents and reused cross-SH documents never spend
    # that capacity.
    structuring_eligibility = fulltext_llm_structuring_eligibility(
        acquired_full_text=acquired_full_text,
        post_alignment=alignment_assessment,
        paper_genre_assessment=paper_genre_assessment,
        bridge_approved=bridge_approved,
        post_fulltext_admission=post_fulltext_admission,
        reused_project_full_text=reused_project_full_text,
        batch_single_flight_reused=batch_single_flight_reused,
    )
    pre_structuring_quality = extraction_quality_report(payload)
    llm_retry: dict[str, Any] = {"attempted": False, "succeeded": False, "error": ""}
    if (
        structuring_eligibility.get("eligible")
        and pre_structuring_quality.get("needs_llm_retry")
        and use_llm
    ):
        log_event(
            "SCIENCE",
            "legacy_fulltext_structuring_llm_started",
            project_id=project_id,
            search_id=search_id,
            result_index=index,
            layer=str(result.get("stratified_layer") or ""),
            role=structuring_eligibility.get("role"),
            title=str(result.get("title") or "")[:120],
        )
        with _V3_RETRIEVAL_LLM_STRUCTURING_SEMAPHORE:
            payload, llm_retry = maybe_llm_reextract_structure(payload, force=True)
        if llm_retry.get("attempted"):
            log_event(
                "WARN" if llm_retry.get("error") else "SCIENCE",
                "legacy_fulltext_structuring_llm_completed",
                project_id=project_id,
                search_id=search_id,
                result_index=index,
                layer=str(result.get("stratified_layer") or ""),
                role=structuring_eligibility.get("role"),
                title=str(result.get("title") or "")[:120],
                status="FAILED" if llm_retry.get("error") else "COMPLETED",
                error=str(llm_retry.get("error") or ""),
            )
    fulltext_structuring = _fulltext_structuring_state(
        eligibility=structuring_eligibility,
        use_llm=use_llm,
        llm_retry=llm_retry,
        deterministic_complete=bool(
            structuring_eligibility.get("eligible")
            and not pre_structuring_quality.get("needs_llm_retry")
        ),
    )
    # A duplicate has a canonical PaperGraph record already.  Its binding
    # records this reuse decision, while the canonical record retains its own
    # completed/pending structuring state rather than being overwritten.
    fulltext_structuring_for_record = (
        None
        if structuring_eligibility.get("role") == "duplicate_reuse_skip"
        else fulltext_structuring
    )
    post_fulltext_admission["fulltext_structuring"] = dict(fulltext_structuring)
    final_extraction_quality = extraction_quality_report(payload)
    final_extraction_quality["initial"] = initial_extraction_quality
    final_extraction_quality["pre_structuring"] = pre_structuring_quality
    final_extraction_quality["llm_retry"] = llm_retry
    final_extraction_quality["fulltext_structuring"] = dict(fulltext_structuring)
    if isinstance(payload.get("_full_text_enrichment"), dict):
        final_extraction_quality["full_text_summary"] = extraction_report_summary(
            payload["_full_text_enrichment"]
        )
    if payload.get("_enrichment_errors"):
        final_extraction_quality["enrichment_errors"] = payload.get("_enrichment_errors")

    paper_classification["admission_status"] = str(
        post_fulltext_admission.get("admission_status")
        or post_fulltext_admission.get("status")
        or "PENDING"
    )
    paper_genre_assessment["admission_status"] = paper_classification["admission_status"]

    commit_kwargs = dict(
        project_id=project_id,
        use_llm=use_llm,
        title=str(payload.get("title", "")),
        citation=str(payload.get("citation", "")),
        authors=payload.get("authors") if isinstance(payload.get("authors"), list) else [],
        year=str(payload.get("year", "")),
        venue=str(payload.get("venue", "")),
        provider=str(payload.get("provider", result.get("provider", "search"))),
        source_type=str(payload.get("source_type", "api")),
        doi=_first_optional_identifier(payload.get("doi"), result.get("doi")),
        arxiv_id=_first_optional_identifier(payload.get("arxiv_id"), result.get("arxiv_id")),
        semantic_scholar_id=_first_optional_identifier(
            payload.get("semantic_scholar_id"), result.get("semantic_scholar_id")
        ),
        openalex_id=_first_optional_identifier(payload.get("openalex_id"), result.get("openalex_id")),
        url=_first_optional_identifier(payload.get("url"), result.get("url")),
        abstract=str(payload.get("abstract", "")),
        full_text_excerpt=str(payload.get("full_text_excerpt", "")),
        open_access_pdf=str(payload.get("open_access_pdf", result.get("open_access_pdf", ""))),
        full_text_enrichment=payload.get("_full_text_enrichment") if isinstance(payload.get("_full_text_enrichment"), dict) else None,
        visual_evidence=(
            payload.get("visual_evidence")
            if isinstance(payload.get("visual_evidence"), list)
            else (
                (payload.get("_full_text_enrichment") or {}).get("visual_evidence")
                if isinstance(payload.get("_full_text_enrichment"), dict)
                and isinstance((payload.get("_full_text_enrichment") or {}).get("visual_evidence"), list)
                else None
            )
        ),
        conclusion=str(payload.get("conclusion", "")),
        strengths=payload.get("strengths") if isinstance(payload.get("strengths"), list) else None,
        improvements=payload.get("improvements") if isinstance(payload.get("improvements"), list) else None,
        method=str(payload.get("method", "")),
        scenario=str(payload.get("scenario", "")),
        benchmark=str(payload.get("benchmark", "")),
        contribution=str(payload.get("contribution", "")),
        limitation=str(payload.get("limitation", "")),
        extraction_quality=final_extraction_quality,
        enrichment_sources=enrichment_sources,
        gap_signals=payload.get("gap_signals") if isinstance(payload.get("gap_signals"), list) else None,
        causal_chains=payload.get("causal_chains") if isinstance(payload.get("causal_chains"), list) else None,
        import_context={
            "search_id": search_id,
            "result_index": index,
            "sub_hypothesis_id": str(
                query_provenance.get("sub_hypothesis_id")
                or (alignment_contract or {}).get("sub_hypothesis_id")
                or retrieval_scope.get("sub_hypothesis_id")
                or ""
            ),
            "stratified_layer": str(result.get("stratified_layer") or ""),
            "query_branch": str(result.get("query_branch") or ""),
            "primary_query_branch": str(result.get("primary_query_branch") or result.get("query_branch") or ""),
            "matched_query_branches": [
                str(value)
                for value in (result.get("matched_query_branches") or [])
                if str(value).strip()
            ],
            "matched_evidence_kinds": [
                str(value)
                for value in (alignment_assessment.get("matched_evidence_kinds") or result.get("matched_evidence_kinds") or [])
                if str(value).strip()
            ],
            "matched_evidence_path_roles": [
                str(value)
                for value in (result.get("matched_evidence_path_roles") or [])
                if str(value).strip()
            ],
            "evidence_path_role": str(result.get("evidence_path_role") or ""),
            "evidence_path_polarity": str(result.get("evidence_path_polarity") or ""),
            "target_lane": str(result.get("target_lane") or ""),
            "target_layer": str(result.get("target_layer") or ""),
            "retrieval_layer_role": str(result.get("retrieval_layer_role") or ""),
            "core_evidence_capable": result.get("core_evidence_capable"),
            "can_independently_falsify_sh": result.get("can_independently_falsify_sh"),
            "failure_scope": str(result.get("failure_scope") or ""),
            "negative_evidence_interpretation": str(result.get("negative_evidence_interpretation") or ""),
            "query_family": str(result.get("query_family") or ""),
            "path_composition_policy": str(result.get("path_composition_policy") or ""),
            "selection_stage": str(result.get("selection_stage") or "pre_import"),
            "research_question_task_id": research_question_task_id,
            "alignment_scope_id": str(
                (alignment_contract or {}).get("alignment_scope_id") or ""
            ),
            "alignment_scope_revision": str(
                (alignment_contract or {}).get("alignment_scope_revision") or ""
            ),
            "object_scope": dict(
                (alignment_contract or {}).get("object_scope") or {}
            ),
            "evidence_slot": evidence_slot,
            "plan_revision": plan_revision,
            "research_question_contract_id": str(
                (alignment_contract or {}).get("contract_id") or ""
            ),
            "research_question_contract_revision": str(
                (alignment_contract or {}).get("contract_revision")
                or (alignment_contract or {}).get("declaration_hash")
                or ""
            ),
            "research_question_contract_hash": str(
                query_provenance.get("research_question_contract_hash")
                or (alignment_contract or {}).get("declaration_hash")
                or (alignment_contract or {}).get("contract_revision")
                or ""
            ),
            "groupchat_id": str(query_provenance.get("groupchat_id") or ""),
            "run_id": str(query_provenance.get("run_id") or ""),
            "retrieval_wave_id": str(query_provenance.get("retrieval_wave_id") or ""),
            "query_branch_id": str(
                query_provenance.get("query_branch_id")
                or result.get("query_branch")
                or ""
            ),
            "query_branch_role": str(query_provenance.get("query_branch_role") or ""),
            "candidate_rank": int(result.get("result_index") or index),
            "provider": str(
                result.get("provider")
                or (result.get("provider_provenance") or {}).get("provider")
                or ""
            ),
            "query_mode": str(task_provenance.get("query_mode") or ""),
            "candidate_research_role": str(
                result.get("candidate_research_role")
                or (
                    str(result.get("research_role") or "UNCLASSIFIED").upper()
                    if str(result.get("research_role") or "").upper().endswith(
                        "_CANDIDATE"
                    )
                    else (
                        f"{str(result.get('research_role') or 'UNCLASSIFIED').upper()}_CANDIDATE"
                    )
                )
            ),
            "targeted_admission_tier": str(
                result.get("targeted_admission_tier")
                or targeted_alignment_admission.get("admission_tier")
                or ""
            ),
            "provisional_evidence_lane": str(
                result.get("provisional_evidence_lane")
                or targeted_alignment_admission.get(
                    "prefulltext_provisional_evidence_lane"
                )
                or ""
            ),
            "detail_revalidation_required": bool(
                result.get("detail_revalidation_required")
                or prefulltext_pending_from_search
            ),
            "independent_evidence_slots_consumed": 1,
            "retrieval_scope": retrieval_scope,
            "post_fulltext_admission": post_fulltext_admission,
        },
        retrieval_query=str(search_record.get("query") or ""),
        domain_relevance=result.get("domain_relevance") if isinstance(result.get("domain_relevance"), dict) else None,
        domain_review=result.get("domain_review") if isinstance(result.get("domain_review"), dict) else None,
        domain_gate=domain_gate,
        domain_override=domain_override,
        research_role=final_research_role,
        research_role_assessment=final_research_role_assessment,
        research_question_card_version=str((search_record.get("research_question_card") or {}).get("version") or ""),
        alignment_assessment=alignment_assessment or None,
        evidence_kind=requested_evidence_kind,
        alignment_override=alignment_override or None,
        foundational_bridge_assessment=(
            bridge_assessment if bridge_requested else None
        ),
        paper_genre_assessment=paper_genre_assessment,
        paper_domain_assessment=paper_domain_assessment,
        paper_classification=paper_classification,
        fulltext_structuring=fulltext_structuring_for_record,
        provider_provenance=(
            payload.get("provider_provenance")
            if isinstance(payload.get("provider_provenance"), dict)
            else (result.get("provider_provenance") if isinstance(result.get("provider_provenance"), dict) else None)
        ),
        external_ids=_normalize_external_identifiers(
            {
                **(
                    result.get("external_ids")
                    if isinstance(result.get("external_ids"), dict)
                    else {}
                ),
                **(
                    payload.get("external_ids")
                    if isinstance(payload.get("external_ids"), dict)
                    else {}
                ),
                **(
                    {
                        kind: values[0]
                        for kind, values in (result.get("paper_identity_aliases") or {}).items()
                        if isinstance(values, list) and values and kind != "title"
                    }
                    if isinstance(result.get("paper_identity_aliases"), dict)
                    else {}
                ),
            }
        ) or None,
        citation_metrics=(
            payload.get("citation_metrics")
            if isinstance(payload.get("citation_metrics"), dict)
            else (result.get("citation_metrics") if isinstance(result.get("citation_metrics"), dict) else None)
        ),
    )
    prepared_paper_id = _prepared_paper_id(commit_kwargs, existing_project_record)
    evidence_preparation_started = time.perf_counter()
    process_rss_before_mb = _process_rss_mb()
    log_event(
        "SCIENCE",
        "candidate_evidence_preparation_started",
        project_id=project_id,
        search_id=search_id,
        result_index=index,
        paper_id=prepared_paper_id,
        stage="document_proposition_and_contract_alignment",
    )
    prepared_evidence_artifact = _prepare_document_evidence_artifact(
        project=project,
        commit_kwargs=commit_kwargs,
        paper_id=prepared_paper_id,
        policy=execution_policy,
        alignment_contract=alignment_contract,
        alignment_contracts=alignment_contracts,
        existing_record=existing_project_record,
        preparation_decision=document_proposition_preparation_decision(
            acquired_full_text=acquired_full_text,
            research_role=final_research_role,
            classification_status=str(
                paper_classification.get("status") or "CLASSIFICATION_PENDING"
            ),
            contract_bound=bool(alignment_contract or alignment_contracts),
        ),
    )
    evidence_preparation_elapsed_ms = round(
        (time.perf_counter() - evidence_preparation_started) * 1000,
        2,
    )
    process_rss_after_mb = _process_rss_mb()
    telemetry_enrichment = (
        commit_kwargs.get("full_text_enrichment")
        if isinstance(commit_kwargs.get("full_text_enrichment"), Mapping)
        else {}
    )
    alignment_artifacts = (
        prepared_evidence_artifact.get("contract_alignment_artifacts")
        if isinstance(prepared_evidence_artifact.get("contract_alignment_artifacts"), Mapping)
        else {}
    )
    alignment_pending_pair_count = sum(
        len({
            *(
                str(item.get("proposition_id") or "")
                + "|"
                + str(item.get("slot_id") or "")
                for item in artifact.get("alignment_decisions", [])
                if isinstance(item, Mapping)
                and str(item.get("verdict") or "").upper() == "PENDING"
            ),
            *(str(item) for item in artifact.get("missing_pair_ids") or []),
            *(str(item) for item in artifact.get("transport_pending_pair_ids") or []),
            *(str(item) for item in artifact.get("response_truncated_pair_ids") or []),
            *(str(item) for item in artifact.get("root_protocol_invalid_pair_ids") or []),
        })
        for alignment_index in alignment_artifacts.values()
        if isinstance(alignment_index, Mapping)
        for artifact in dict(alignment_index.get("task_alignments") or {}).values()
        if isinstance(artifact, Mapping)
    )
    log_event(
        "SCIENCE",
        "candidate_evidence_preparation_completed",
        project_id=project_id,
        search_id=search_id,
        result_index=index,
        paper_id=prepared_paper_id,
        stage="document_proposition_and_contract_alignment",
        elapsed_ms=evidence_preparation_elapsed_ms,
        extraction_status=str(prepared_evidence_artifact.get("extraction_status") or ""),
        proposition_count=len(prepared_evidence_artifact.get("propositions") or []),
        assertion_candidate_count=len(prepared_evidence_artifact.get("assertion_candidates") or []),
        verified_assertion_count=len(prepared_evidence_artifact.get("assertions") or []),
        assertion_count=len(prepared_evidence_artifact.get("assertions") or []),
        alignment_pending_pair_count=alignment_pending_pair_count,
        canonical_text_chars=len(
            str(
                telemetry_enrichment.get("canonical_text")
                or commit_kwargs.get("full_text_excerpt")
                or ""
            )
        ),
        raw_layout_bytes=_serialized_json_size_bytes(
            telemetry_enrichment.get("raw_layout_pages") or []
        ),
        source_fragment_count=len(
            telemetry_enrichment.get("fragment_registry") or []
        ),
        source_span_count=len(prepared_evidence_artifact.get("source_spans") or []),
        process_rss_before_mb=process_rss_before_mb,
        process_rss_peak_mb=max(process_rss_before_mb, process_rss_after_mb),
    )
    commit_kwargs["prepared_paper_id"] = prepared_paper_id
    commit_kwargs["document_descriptor"] = dict(
        prepared_evidence_artifact.get("document_descriptor") or {}
    )
    commit_kwargs["prepared_evidence_artifact"] = prepared_evidence_artifact
    response_metadata = {
        "search_result_quality": quality,
        "extraction_quality": final_extraction_quality,
        "enrichment_sources": enrichment_sources,
        "requires_human_review": (
        quality["venue_quality"] in {"suspicious", "missing"}
        or quality["quality_score"] < 0.55
        or bool(final_extraction_quality.get("requires_human_review"))
        or str(domain_gate.get("verdict") or "") in {"review", "override"}
        or str(domain_review.get("verdict") or "") == "review"
        or ad_hoc_discovery
        ),
        "post_fulltext_admission": post_fulltext_admission,
        "fulltext_structuring": dict(fulltext_structuring),
        "alignment_assessment": dict(alignment_assessment or {}),
        "corpus_admitted": bool((alignment_assessment or {}).get("corpus_admitted")),
        "corpus_admission_reason": str((alignment_assessment or {}).get("corpus_admission_reason") or ""),
        "evidence_role": str((alignment_assessment or {}).get("evidence_role") or ""),
        "gate_counting_evidence": bool((alignment_assessment or {}).get("gate_counting_evidence")),
        "foundational_bridge_assessment": (
            dict(bridge_assessment) if bridge_requested else {}
        ),
        "paper_domain_assessment": dict(paper_domain_assessment),
        "paper_classification": dict(paper_classification),
        "prepared_paper_id": prepared_paper_id,
        "evidence_preparation_elapsed_ms": evidence_preparation_elapsed_ms,
        "pre_download_duplicate": isinstance(existing_project_record, dict),
        "reused_project_full_text": reused_project_full_text,
    }
    return {
        "status": "prepared",
        "schema_version": "prepared_evidence_candidate_v3",
        "project_id": project_id,
        "search_id": search_id,
        "result_index": index,
        "base_state_version": int(project.get("state_version") or 0),
        "candidate_identity": dict(identity_candidate),
        "paper_classification": dict(paper_classification),
        "domain_assessment": dict(paper_domain_assessment),
        "document_descriptor": dict(
            prepared_evidence_artifact.get("document_descriptor") or {}
        ),
        "document_artifact_refs": dict(
            prepared_evidence_artifact.get("document_artifact_refs") or {}
        ),
        "proposition_artifact_ref": {
            "artifact_id": str(
                (prepared_evidence_artifact.get("document_proposition_artifact") or {}).get("artifact_id")
                or ""
            ),
            "status": str(prepared_evidence_artifact.get("extraction_status") or ""),
            "path": str(
                (prepared_evidence_artifact.get("document_artifact_refs") or {}).get(
                    "proposition_artifact_ref"
                )
                or ""
            ),
        },
        "contract_alignment_artifact": dict(
            prepared_evidence_artifact.get("contract_alignment_artifacts") or {}
        ),
        "admission_decision": dict(
            prepared_evidence_artifact.get("gap_source_admissions_v4") or {}
        ),
        "diagnostics": {
            "evidence_preparation_elapsed_ms": evidence_preparation_elapsed_ms,
            "reason_codes": list(prepared_evidence_artifact.get("reason_codes") or []),
        },
        "identity_aliases": paper_identity_alias_keys(identity_candidate),
        "commit_kwargs": commit_kwargs,
        "response_metadata": response_metadata,
    }


def prepare_literature_candidate_metadata_only(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Prepare only deterministic/metadata admission; never run OA/PDF work."""

    kwargs["include_full_text"] = False
    return prepare_literature_candidate(*args, **kwargs)


def prepare_literature_candidate_fulltext(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Prepare a gate-potential candidate with full-text acquisition enabled."""

    kwargs["include_full_text"] = True
    return prepare_literature_candidate(*args, **kwargs)


def _v3_preparation_item(
    *,
    project_id: str,
    search_id: str,
    result_index: int,
    candidate_key: str,
    project_snapshot: dict[str, Any],
    search_record_snapshot: dict[str, Any],
    identity_index_snapshot: Mapping[str, dict[str, Any]],
    use_llm: bool,
    query_branch_override: str,
    alignment_contract: dict[str, Any] | None,
    alignment_contracts: list[dict[str, Any]] | None,
    evidence_kind_override: str,
    single_flight: LiteraturePreparationSingleFlight,
) -> dict[str, Any]:
    """Prepare one V3 candidate without mutating the shared project state."""

    started_at = time.perf_counter()
    try:
        prepared = prepare_literature_candidate_fulltext(
            project_id=project_id,
            search_id=search_id,
            result_index=result_index,
            use_llm=use_llm,
            query_branch_override=query_branch_override,
            alignment_contract=alignment_contract,
            alignment_contracts=alignment_contracts,
            evidence_kind_override=evidence_kind_override,
            project=project_snapshot,
            search_record=search_record_snapshot,
            identity_index=identity_index_snapshot,
            single_flight=single_flight,
        )
        status = str(prepared.get("status") or "terminal")
        response_metadata = (
            prepared.get("response_metadata")
            if isinstance(prepared.get("response_metadata"), dict)
            else {}
        )
        structuring = (
            response_metadata.get("fulltext_structuring")
            if isinstance(response_metadata.get("fulltext_structuring"), dict)
            else {}
        )
        return {
            "result_index": result_index,
            "candidate_key": candidate_key,
            "status": status,
            "prepared": prepared,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "error": "",
            "reused_project_full_text": bool(
                response_metadata.get("reused_project_full_text")
            ),
            "fulltext_available": bool(
                (prepared.get("commit_kwargs") or {}).get("full_text_excerpt")
            ),
            "llm_structured": str(structuring.get("status") or "")
            == "structured_by_llm",
        }
    except Exception as exc:
        return {
            "result_index": result_index,
            "candidate_key": candidate_key,
            "status": "failed",
            "prepared": {},
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            "reused_project_full_text": False,
            "fulltext_available": False,
            "llm_structured": False,
        }


def prepare_v3_literature_candidate_batch(
    *,
    project: dict[str, Any],
    search_record: dict[str, Any],
    candidates: list[dict[str, Any]],
    project_id: str,
    search_id: str,
    use_llm: bool,
    query_branch_override: str,
    alignment_contract: dict[str, Any] | None,
    alignment_contracts: list[dict[str, Any]] | None = None,
    evidence_kind_override: str = "",
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Prepare a deterministic V3 candidate batch without project writes.

    Network resolution, PDF parsing, and eligible LLM structuring can overlap,
    but every worker sees a fixed read-only project/search snapshot.  Evidence
    bindings and artifact state are deliberately deferred to the serial commit
    phase below.
    """

    ordered_candidates = [
        dict(candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    project_snapshot = deepcopy(project)
    search_snapshot = deepcopy(search_record)
    identity_snapshot = build_project_paper_identity_index(project_snapshot)
    requested_workers = max_workers if max_workers is not None else V3_RETRIEVAL_PREPARATION_WORKERS
    workers = max(1, min(int(requested_workers or 1), len(ordered_candidates) or 1))
    single_flight = LiteraturePreparationSingleFlight()
    started_at = time.perf_counter()
    contract = deepcopy(alignment_contract) if isinstance(alignment_contract, dict) else None
    batch = {
        "schema_version": "v3_prepared_literature_candidate_batch_v1",
        "project_id": project_id,
        "search_id": search_id,
        "base_state_version": int(project.get("state_version") or 0),
        "sub_hypothesis_id": str((contract or {}).get("sub_hypothesis_id") or ""),
        "research_question_contract_id": str((contract or {}).get("contract_id") or ""),
        "research_question_contract_hash": str(
            (contract or {}).get("declaration_hash")
            or (contract or {}).get("contract_revision")
            or (contract or {}).get("contract_hash")
            or ""
        ),
        "query_branch": query_branch_override,
        "research_question_task_id": str(
            (contract or {}).get("research_question_task_id") or ""
        ),
        "evidence_slot": str((contract or {}).get("evidence_slot") or ""),
        "plan_revision": str((contract or {}).get("plan_revision") or ""),
        "review_mode": (
            "SH_MULTI_TASK_COMPACT"
            if alignment_contracts
            else "TASK_SINGLE_SLOT"
        ),
        "alignment_contract_count": len(alignment_contracts or []) or (1 if contract else 0),
        "requested_count": len(ordered_candidates),
        "max_workers": workers,
        "items": [],
    }
    if not ordered_candidates:
        batch["elapsed_ms"] = 0.0
        return batch

    log_event(
        "SCIENCE",
        "v3_candidate_preparation_batch_started",
        project_id=project_id,
        search_id=search_id,
        sub_hypothesis_id=batch["sub_hypothesis_id"],
        research_question_task_id=batch["research_question_task_id"],
        evidence_slot=batch["evidence_slot"],
        plan_revision=batch["plan_revision"],
        query_branch=query_branch_override,
        candidate_count=len(ordered_candidates),
        max_workers=workers,
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _v3_preparation_item,
                project_id=project_id,
                search_id=search_id,
                result_index=int(candidate.get("result_index") or 0),
                candidate_key=str(candidate.get("_v3_candidate_key") or ""),
                project_snapshot=project_snapshot,
                search_record_snapshot=search_snapshot,
                identity_index_snapshot=identity_snapshot,
                use_llm=use_llm,
                query_branch_override=query_branch_override,
                alignment_contract=contract,
                alignment_contracts=(
                    [dict(item) for item in (alignment_contracts or []) if isinstance(item, Mapping)]
                    if alignment_contracts
                    else None
                ),
                evidence_kind_override=evidence_kind_override,
                single_flight=single_flight,
            ): candidate
            for candidate in ordered_candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                item = {
                    "result_index": int(candidate.get("result_index") or 0),
                    "candidate_key": str(candidate.get("_v3_candidate_key") or ""),
                    "status": "failed",
                    "prepared": {},
                    "elapsed_ms": 0.0,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            batch["items"].append(item)
            log_event(
                "SCIENCE",
                "v3_candidate_prepared",
                project_id=project_id,
                search_id=search_id,
                sub_hypothesis_id=batch["sub_hypothesis_id"],
                research_question_task_id=batch["research_question_task_id"],
                evidence_slot=batch["evidence_slot"],
                plan_revision=batch["plan_revision"],
                query_branch=query_branch_override,
                result_index=item["result_index"],
                preparation_status=item["status"],
                elapsed_ms=item["elapsed_ms"],
                error=item["error"][:180],
            )
    batch["items"].sort(key=lambda item: int(item.get("result_index") or 0))
    batch["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    batch["prepared_count"] = sum(
        1 for item in batch["items"] if item.get("status") == "prepared"
    )
    batch["terminal_count"] = sum(
        1 for item in batch["items"] if item.get("status") == "terminal"
    )
    batch["failed_count"] = sum(
        1 for item in batch["items"] if item.get("status") == "failed"
    )
    batch["reused_fulltext_count"] = sum(
        1 for item in batch["items"] if item.get("reused_project_full_text")
    )
    batch["fulltext_available_count"] = sum(
        1 for item in batch["items"] if item.get("fulltext_available")
    )
    batch["llm_structured_count"] = sum(
        1 for item in batch["items"] if item.get("llm_structured")
    )
    log_event(
        "SCIENCE",
        "v3_candidate_preparation_batch_completed",
        project_id=project_id,
        search_id=search_id,
        sub_hypothesis_id=batch["sub_hypothesis_id"],
        research_question_task_id=batch["research_question_task_id"],
        evidence_slot=batch["evidence_slot"],
        plan_revision=batch["plan_revision"],
        query_branch=query_branch_override,
        candidate_count=len(ordered_candidates),
        prepared_count=batch["prepared_count"],
        terminal_count=batch["terminal_count"],
        failed_count=batch["failed_count"],
        reused_fulltext_count=batch["reused_fulltext_count"],
        fulltext_available_count=batch["fulltext_available_count"],
        llm_structured_count=batch["llm_structured_count"],
        elapsed_ms=batch["elapsed_ms"],
    )
    return batch


def commit_v3_prepared_literature_candidate_batch(
    prepared_batch: Mapping[str, Any],
    *,
    project: dict[str, Any],
    save_project_callback: Callable[[dict[str, Any]], None],
    commit_batch_size: int | None = None,
) -> dict[str, Any]:
    """Commit a prepared V3 batch in original rank order using one writer.

    The shared project, identity index, V3 bindings, SourceSpans, assertions,
    and normalized artifact writes remain exclusive to this caller.  A batch
    save creates a recoverable checkpoint without allowing workers to write.
    """

    project_id = str(prepared_batch.get("project_id") or "")
    if project_id != str(project.get("project_id") or ""):
        raise ValueError("Prepared V3 candidate batch project_id does not match commit project")
    base_version = int(prepared_batch.get("base_state_version") or 0)
    current_version = int(project.get("state_version") or 0)
    if base_version != current_version:
        raise ValueError(
            f"Prepared V3 candidate batch is stale: base_state_version={base_version}, "
            f"current_state_version={current_version}"
        )
    expected_contract_id = str(
        prepared_batch.get("research_question_contract_id") or ""
    )
    expected_contract_hash = str(
        prepared_batch.get("research_question_contract_hash") or ""
    )
    expected_subhypothesis_id = str(
        prepared_batch.get("sub_hypothesis_id") or ""
    )
    if expected_subhypothesis_id and (expected_contract_id or expected_contract_hash):
        current_subhypothesis = next(
            (
                item
                for item in project.get("sub_hypotheses", [])
                if isinstance(item, dict)
                and str(item.get("id") or item.get("sub_hypothesis_id") or "")
                == expected_subhypothesis_id
            ),
            None,
        )
        current_contract = (
            current_subhypothesis.get("research_question_contract")
            if isinstance(current_subhypothesis, dict)
            and isinstance(current_subhypothesis.get("research_question_contract"), dict)
            else {}
        )
        current_contract_hash = str(
            current_contract.get("declaration_hash")
            or current_contract.get("contract_revision")
            or current_contract.get("contract_hash")
            or ""
        )
        if (
            not current_contract
            or (expected_contract_id and str(current_contract.get("contract_id") or "") != expected_contract_id)
            or (expected_contract_hash and current_contract_hash != expected_contract_hash)
        ):
            raise ValueError(
                "Prepared V3 candidate batch contract no longer matches the "
                "current sub-hypothesis declaration"
            )
    identity_index = build_project_paper_identity_index(project)
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    state_manager = science_state_manager()
    del save_project_callback
    items = [dict(item) for item in prepared_batch.get("items", []) if isinstance(item, dict)]
    items.sort(key=lambda item: int(item.get("result_index") or 0))
    size = max(1, int(commit_batch_size or FULLTEXT_COMMIT_BATCH_SIZE))
    started_at = time.perf_counter()
    outcome = {
        "schema_version": "v3_prepared_literature_candidate_commit_v1",
        "project_id": project_id,
        "search_id": str(prepared_batch.get("search_id") or ""),
        "sub_hypothesis_id": str(prepared_batch.get("sub_hypothesis_id") or ""),
        "query_branch": str(prepared_batch.get("query_branch") or ""),
        "research_question_task_id": str(
            prepared_batch.get("research_question_task_id") or ""
        ),
        "evidence_slot": str(prepared_batch.get("evidence_slot") or ""),
        "plan_revision": str(prepared_batch.get("plan_revision") or ""),
        "results": [],
        "persist_count": 0,
        "committed_count": 0,
        "terminal_count": 0,
        "failed_count": 0,
    }
    dirty_count = 0
    pending_commit_events: list[tuple[int, dict[str, Any]]] = []

    def persist_pending_commits() -> None:
        nonlocal dirty_count
        if not pending_commit_events:
            return
        log_event(
            "SCIENCE",
            "candidate_checkpoint_started",
            project_id=project_id,
            search_id=outcome["search_id"],
            sub_hypothesis_id=outcome["sub_hypothesis_id"],
            research_question_task_id=outcome["research_question_task_id"],
            evidence_slot=outcome["evidence_slot"],
            plan_revision=outcome["plan_revision"],
            query_branch=outcome["query_branch"],
            pending_count=len(pending_commit_events),
        )
        persisted_count = 0
        for committed_result_index, committed_payload in pending_commit_events:
            record = (
                committed_payload.get("record")
                if isinstance(committed_payload.get("record"), dict)
                else {}
            )
            paper_id = str(record.get("paper_id") or committed_payload.get("paper_id") or "")
            papergraph = project.get("papergraph") if isinstance(project.get("papergraph"), list) else []
            paper_index = next(
                (
                    index for index, item in enumerate(papergraph)
                    if isinstance(item, dict)
                    and str(item.get("paper_id") or "") == paper_id
                ),
                -1,
            )
            if paper_index < 0:
                raise ValueError(
                    f"Incremental candidate transaction cannot locate materialized paper {paper_id}"
                )
            evidence_values = (
                project.get("evidence") if isinstance(project.get("evidence"), list) else []
            )
            evidence_index = next(
                (
                    index for index, item in enumerate(evidence_values)
                    if isinstance(item, dict)
                    and str(item.get("paper_id") or "") == paper_id
                ),
                -1,
            )
            evidence_record = (
                evidence_values[evidence_index]
                if evidence_index >= 0 and isinstance(evidence_values[evidence_index], dict)
                else None
            )
            receipt = state_manager.commit_prepared_candidate(
                project_id,
                paper=papergraph[paper_index],
                evidence_record=evidence_record,
                expected_version=int(project.get("state_version") or 0),
            )
            project["state_version"] = int(
                receipt.get("state_version") or project.get("state_version") or 0
            )
            project["state_context"] = {
                "store_id": str(project.get("state_store_id") or ""),
                "loaded_version": int(project["state_version"]),
            }
            if isinstance(receipt.get("paper"), dict):
                papergraph[paper_index] = receipt["paper"]
                committed_payload["record"] = receipt["paper"]
                register_project_paper_identity(identity_index, receipt["paper"])
            if evidence_index >= 0 and isinstance(receipt.get("evidence_record"), dict):
                evidence_values[evidence_index] = receipt["evidence_record"]
            committed_payload["commit_receipt"] = {
                "new_state_version": int(receipt.get("state_version") or 0),
                "paper_ref": dict(receipt.get("paper_ref") or {}),
                "artifact_refs": dict(receipt.get("artifact_refs") or {}),
                "commit_status": str(receipt.get("status") or ""),
            }
            metrics = dict(receipt.get("metrics") or {})
            outcome["persist_count"] += 1
            persisted_count += 1
            log_event(
                "SCIENCE",
                "candidate_committed",
                project_id=project_id,
                search_id=outcome["search_id"],
                sub_hypothesis_id=outcome["sub_hypothesis_id"],
                research_question_task_id=outcome["research_question_task_id"],
                evidence_slot=outcome["evidence_slot"],
                plan_revision=outcome["plan_revision"],
                query_branch=outcome["query_branch"],
                result_index=committed_result_index,
                commit_status=str(committed_payload.get("status") or ""),
                state_version=int(project.get("state_version") or 0),
                **metrics,
            )
        log_event(
            "SCIENCE",
            "candidate_checkpoint_persisted",
            project_id=project_id,
            search_id=outcome["search_id"],
            sub_hypothesis_id=outcome["sub_hypothesis_id"],
            research_question_task_id=outcome["research_question_task_id"],
            evidence_slot=outcome["evidence_slot"],
            plan_revision=outcome["plan_revision"],
            query_branch=outcome["query_branch"],
            persisted_count=persisted_count,
            persist_count=outcome["persist_count"],
            state_version=int(project.get("state_version") or 0),
        )
        pending_commit_events.clear()
        dirty_count = 0

    for item in items:
        item_status = str(item.get("status") or "")
        result_index = int(item.get("result_index") or 0)
        if item_status != "prepared":
            outcome["results"].append({
                "result_index": result_index,
                "status": item_status or "terminal",
                "error": str(item.get("error") or ""),
            })
            if item_status == "failed":
                outcome["failed_count"] += 1
            else:
                outcome["terminal_count"] += 1
            continue
        prepared = item.get("prepared") if isinstance(item.get("prepared"), dict) else {}
        try:
            log_event(
                "SCIENCE",
                "candidate_materialization_started",
                project_id=project_id,
                search_id=outcome["search_id"],
                sub_hypothesis_id=outcome["sub_hypothesis_id"],
                research_question_task_id=outcome["research_question_task_id"],
                evidence_slot=outcome["evidence_slot"],
                plan_revision=outcome["plan_revision"],
                query_branch=outcome["query_branch"],
                result_index=result_index,
            )
            committed = commit_prepared_literature_candidate(
                prepared,
                project=project,
                identity_index=identity_index,
                save=False,
                validated_batch_base_state_version=base_version,
            )
        except Exception as exc:
            outcome["results"].append({
                "result_index": result_index,
                "status": "commit_failed",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            })
            outcome["failed_count"] += 1
            log_event(
                "WARN",
                "v3_candidate_commit_failed",
                project_id=project_id,
                search_id=outcome["search_id"],
                sub_hypothesis_id=outcome["sub_hypothesis_id"],
                research_question_task_id=outcome["research_question_task_id"],
                evidence_slot=outcome["evidence_slot"],
                plan_revision=outcome["plan_revision"],
                query_branch=outcome["query_branch"],
                result_index=result_index,
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
            )
            continue
        outcome["results"].append({
            "result_index": result_index,
            "status": str(committed.get("status") or "committed"),
            "imported": committed,
        })
        if str(committed.get("status") or "") == "commit_rejected":
            outcome["terminal_count"] += 1
            log_event(
                "WARN",
                "v3_candidate_commit_rejected",
                project_id=project_id,
                search_id=outcome["search_id"],
                result_index=result_index,
                protocol_status=str(committed.get("protocol_status") or ""),
                reason_codes=list(committed.get("reason_codes") or []),
            )
            continue
        outcome["committed_count"] += 1
        dirty_count += 1
        log_event(
            "SCIENCE",
            "candidate_materialization_completed",
            project_id=project_id,
            search_id=outcome["search_id"],
            sub_hypothesis_id=outcome["sub_hypothesis_id"],
            research_question_task_id=outcome["research_question_task_id"],
            evidence_slot=outcome["evidence_slot"],
            plan_revision=outcome["plan_revision"],
            query_branch=outcome["query_branch"],
            result_index=result_index,
            commit_status=str(committed.get("status") or ""),
        )
        pending_commit_events.append((result_index, committed))
        if dirty_count >= size:
            persist_pending_commits()
    if dirty_count:
        persist_pending_commits()
    outcome["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    log_event(
        "SCIENCE",
        "v3_candidate_batch_completed",
        project_id=project_id,
        search_id=outcome["search_id"],
        sub_hypothesis_id=outcome["sub_hypothesis_id"],
        research_question_task_id=outcome["research_question_task_id"],
        evidence_slot=outcome["evidence_slot"],
        plan_revision=outcome["plan_revision"],
        query_branch=outcome["query_branch"],
        committed_count=outcome["committed_count"],
        terminal_count=outcome["terminal_count"],
        failed_count=outcome["failed_count"],
        persist_count=outcome["persist_count"],
        elapsed_ms=outcome["elapsed_ms"],
    )
    return outcome


def _corpus_evidence_tier_for_import(
    record: Mapping[str, Any],
    alignment: Mapping[str, Any] | None,
    *,
    layer: str,
) -> str:
    assessment = alignment if isinstance(alignment, Mapping) else {}
    type_evidence = (
        assessment.get("type_directed_evidence")
        if isinstance(assessment.get("type_directed_evidence"), Mapping)
        else {}
    )
    direct_contract_core = bool(
        assessment.get("core_eligible") is True
        and type_evidence.get("direct_evidence_eligible") is True
        and str(
            assessment.get("evidence_lane")
            or type_evidence.get("evidence_lane")
            or ""
        )
        == "TYPE_DIRECTED_PRIMARY_SOURCE_EVIDENCE"
    )
    if direct_contract_core:
        return "CORE_CONTRACT_SOURCE"
    role_text = " ".join(
        str(value or "")
        for value in (
            record.get("evidence_role"),
            record.get("evidence_path_role"),
            record.get("evidence_kind"),
            record.get("target_lane"),
            assessment.get("evidence_role"),
            assessment.get("evidence_path_role"),
            assessment.get("evidence_kind"),
            assessment.get("evidence_lane"),
            assessment.get("corpus_admission_reason"),
        )
    ).lower()
    polarity = str(
        record.get("evidence_polarity")
        or assessment.get("evidence_polarity")
        or ""
    ).lower()
    if assessment.get("panel_component_support_only") is True or any(
        marker in role_text
        for marker in ("panel_component", "component_support")
    ):
        return "COMPONENT_SUPPORT"
    if "adverse" in role_text or "reversal" in role_text or polarity == "opposing":
        return "ADVERSE_OR_REVERSAL"
    if (
        "boundary" in role_text
        or "generalization" in role_text
        or polarity == "boundary"
    ):
        return "BOUNDARY_OR_NEGATIVE"
    if layer == "L0_review" or any(
        marker in role_text
        for marker in ("background", "review", "framework", "theoretical")
    ):
        return "BACKGROUND_OR_REVIEW"
    if any(
        marker in role_text
        for marker in (
            "method",
            "platform",
            "foundation",
            "benchmark",
            "calibration",
        )
    ):
        return "METHOD_OR_PLATFORM"
    if any(
        marker in role_text
        for marker in (
            "component",
            "bridge",
            "type_directed_component_bridge",
        )
    ):
        return "COMPONENT_BRIDGE"
    return "RELATED_CONTEXT"


def _alignment_relatedness_axes_for_log(alignment: Mapping[str, Any] | None) -> list[str]:
    assessment = alignment if isinstance(alignment, Mapping) else {}
    corpus = (
        assessment.get("corpus_admission")
        if isinstance(assessment.get("corpus_admission"), Mapping)
        else {}
    )
    axes = corpus.get("relatedness_axes") if isinstance(corpus.get("relatedness_axes"), Mapping) else {}
    return [
        str(key)
        for key, value in axes.items()
        if isinstance(value, list) and value
    ]


def _alignment_missing_contract_requirements_for_log(alignment: Mapping[str, Any] | None) -> list[str]:
    assessment = alignment if isinstance(alignment, Mapping) else {}
    return type_directed_missing_axes({}, assessment)


def _noncore_demotion_reason_for_log(
    alignment: Mapping[str, Any] | None,
    missing_requirements: list[str],
) -> str:
    assessment = alignment if isinstance(alignment, Mapping) else {}
    if missing_requirements:
        return "missing_" + "_and_".join(
            requirement.replace("declared_", "")
            for requirement in missing_requirements[:3]
        )
    verdict = str(assessment.get("verdict") or "").strip()
    return verdict.lower() if verdict else "noncore_related_evidence"


def _safe_visual_evidence_units(
    visual_evidence: list[dict[str, Any]] | None,
    *,
    paper_id: str = "",
    sub_hypothesis_id: str = "",
    source_pdf_url: str = "",
) -> list[dict[str, Any]]:
    """Persist visual units without giving the vision branch gate authority."""

    allowed_scopes = {
        "visual_project_background_only",
        "visual_sh_local_auxiliary",
        "visual_component_bridge_candidate",
        "visual_core_candidate_pending_review",
    }
    schematic_types = {"schematic", "flow_diagram"}
    units: list[dict[str, Any]] = []
    for index, item in enumerate(visual_evidence or [], start=1):
        if not isinstance(item, dict):
            continue
        unit = dict(item)
        unit["paper_id"] = str(unit.get("paper_id") or paper_id or "")
        if sub_hypothesis_id and not unit.get("sub_hypothesis_id"):
            unit["sub_hypothesis_id"] = str(sub_hypothesis_id)
        if source_pdf_url and not unit.get("source_pdf_url"):
            unit["source_pdf_url"] = str(source_pdf_url)
        unit.setdefault(
            "visual_id",
            f"{unit.get('paper_id') or 'paper'}_visual_{index}",
        )
        scope = str(unit.get("admission_scope") or unit.get("evidence_role") or "")
        if scope not in allowed_scopes:
            scope = "visual_project_background_only"
        if (
            str(unit.get("visual_type") or "").lower() in schematic_types
            and scope == "visual_core_candidate_pending_review"
        ):
            scope = "visual_sh_local_auxiliary"
            unit["direct_core_pending_human_review"] = False
        unit["admission_scope"] = scope
        unit["evidence_role"] = scope
        unit["excluded_from_sh_gap_synthesis"] = bool(
            unit.get("excluded_from_sh_gap_synthesis")
            or scope == "visual_project_background_only"
        )
        unit["counts_toward_gate"] = False
        unit["counts_toward_corpus_target"] = False
        unit["excluded_from_direct_core_gate"] = True
        unit["requires_human_review"] = True
        unit["core_eligible"] = False
        unit["standard_core_eligible"] = False
        if scope != "visual_core_candidate_pending_review":
            unit["direct_core_pending_human_review"] = False
        unit.setdefault(
            "human_visual_review",
            {
                "status": "not_requested",
                "reviewer": "",
                "reviewed_at": None,
                "notes": "",
                "approved_claims": [],
            },
        )
        units.append(unit)
    return units


def _visual_evidence_summary(visual_evidence: list[dict[str, Any]] | None) -> dict[str, Any]:
    summary = {
        "visual_project_background_only": 0,
        "visual_sh_local_auxiliary": 0,
        "visual_component_bridge_candidate": 0,
        "visual_core_candidate_pending_review": 0,
        "total": 0,
        "counts_toward_gate": False,
        "requires_human_review": True,
    }
    for item in visual_evidence or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("admission_scope") or "visual_project_background_only")
        if scope not in summary:
            scope = "visual_project_background_only"
        summary[scope] += 1
        summary["total"] += 1
    return summary


def commit_prepared_literature_candidate(
    prepared: Mapping[str, Any],
    *,
    project: dict[str, Any] | None = None,
    identity_index: dict[str, dict[str, Any]] | None = None,
    save: bool = True,
    validated_batch_base_state_version: int | None = None,
) -> dict[str, Any]:
    """Serially materialize one prepared candidate into the shared project.

    Standalone commits validate against the project's current state version.
    A batch writer instead supplies the state version validated before the
    batch started, because its own checkpoints legitimately advance the
    mutable project version while sibling candidates retain that shared base.
    """

    if str(prepared.get("status") or "") != "prepared":
        response = prepared.get("response")
        if isinstance(response, dict):
            return deepcopy(response)
        raise ValueError("Prepared literature candidate has no committable payload")
    prepared_base_state_version = prepared.get("base_state_version")
    if validated_batch_base_state_version is not None:
        if prepared_base_state_version is None:
            raise ValueError(
                "Prepared evidence candidate is missing base_state_version for batch commit"
            )
        if int(prepared_base_state_version or 0) != int(validated_batch_base_state_version):
            raise ValueError(
                "Prepared evidence candidate does not belong to the validated batch state"
            )
    elif isinstance(project, dict) and prepared_base_state_version is not None:
        if int(prepared_base_state_version or 0) != int(project.get("state_version") or 0):
            raise ValueError("Prepared evidence candidate is stale relative to project state")
    commit_kwargs = prepared.get("commit_kwargs")
    if not isinstance(commit_kwargs, dict):
        raise ValueError("Prepared literature candidate is missing commit_kwargs")
    materialization_kwargs = dict(commit_kwargs)
    materialization_kwargs.pop("use_llm", None)
    imported = import_papergraph_record(
        **materialization_kwargs,
        project=project,
        identity_index=identity_index,
        save=False,
    )
    imported_payload = json.loads(imported)
    if (
        not isinstance(imported_payload.get("record"), dict)
        and isinstance(imported_payload.get("existing_record"), dict)
    ):
        imported_payload["record"] = imported_payload["existing_record"]
    if (
        save
        and isinstance(project, dict)
        and str(imported_payload.get("status") or "") != "commit_rejected"
    ):
        imported_record = (
            imported_payload.get("record")
            if isinstance(imported_payload.get("record"), dict)
            else {}
        )
        paper_id = str(
            imported_record.get("paper_id")
            or imported_payload.get("paper_id")
            or ""
        )
        papergraph = project.get("papergraph") if isinstance(project.get("papergraph"), list) else []
        paper_index = next(
            (
                index for index, item in enumerate(papergraph)
                if isinstance(item, dict)
                and str(item.get("paper_id") or "") == paper_id
            ),
            -1,
        )
        if paper_index >= 0:
            evidence_values = project.get("evidence") if isinstance(project.get("evidence"), list) else []
            evidence_index = next(
                (
                    index for index, item in enumerate(evidence_values)
                    if isinstance(item, dict)
                    and str(item.get("paper_id") or "") == paper_id
                ),
                -1,
            )
            try:
                from ._project import science_state_manager
            except ImportError:
                from _project import science_state_manager
            receipt = science_state_manager().commit_prepared_candidate(
                str(project.get("project_id") or prepared.get("project_id") or ""),
                paper=papergraph[paper_index],
                evidence_record=(
                    evidence_values[evidence_index] if evidence_index >= 0 else None
                ),
                expected_version=int(project.get("state_version") or 0),
            )
            project["state_version"] = int(receipt.get("state_version") or 0)
            project["state_context"] = {
                "store_id": str(project.get("state_store_id") or ""),
                "loaded_version": int(project["state_version"]),
            }
            if isinstance(receipt.get("paper"), dict):
                papergraph[paper_index] = receipt["paper"]
                imported_payload["record"] = receipt["paper"]
            if evidence_index >= 0 and isinstance(receipt.get("evidence_record"), dict):
                evidence_values[evidence_index] = receipt["evidence_record"]
            imported_payload["commit_receipt"] = {
                "new_state_version": int(receipt.get("state_version") or 0),
                "paper_ref": dict(receipt.get("paper_ref") or {}),
                "artifact_refs": dict(receipt.get("artifact_refs") or {}),
                "commit_status": str(receipt.get("status") or ""),
            }
    response_metadata = prepared.get("response_metadata")
    if isinstance(response_metadata, dict):
        imported_payload.update(deepcopy(response_metadata))
    return imported_payload


def import_literature_search_result(
    project_id: str,
    search_id: str,
    result_index: int = 0,
    use_llm: bool | None = None,
    enable_focal_variable_synonym_dictionary: bool | None = None,
    stratified_layer_override: str = "",
    query_branch_override: str = "",
    alignment_contract: dict[str, Any] | None = None,
    evidence_kind_override: str = "",
    foundational_bridge_assessment: dict[str, Any] | None = None,
    force_import: bool = False,
) -> str:
    """Compatibility wrapper for callers that still import one paper at a time."""

    try:
        from ._project import load_project, load_search, science_state_manager
    except ImportError:
        from _project import load_project, load_search, science_state_manager
    try:
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _science_execution_policy import resolve_science_execution_policy
    project = load_project(project_id)
    use_llm = resolve_science_execution_policy(project, use_llm=use_llm).use_llm
    search_record = load_search(search_id)
    identity_index = build_project_paper_identity_index(project)
    prepared = prepare_literature_candidate(
        project_id=project_id,
        search_id=search_id,
        result_index=result_index,
        use_llm=use_llm,
        enable_focal_variable_synonym_dictionary=enable_focal_variable_synonym_dictionary,
        stratified_layer_override=stratified_layer_override,
        query_branch_override=query_branch_override,
        alignment_contract=alignment_contract,
        evidence_kind_override=evidence_kind_override,
        foundational_bridge_assessment=foundational_bridge_assessment,
        force_import=force_import,
        project=project,
        search_record=search_record,
        identity_index=identity_index,
    )
    # The focal-variable dictionary is generated at contract scope, not per
    # paper.  A normal commit persists the same in-memory project snapshot.
    # Only an early rejection needs a standalone save, otherwise a later
    # candidate would repeat the same LLM request for this SH.
    synonym_policy = (
        alignment_contract.get("core_axis_policy")
        if isinstance(alignment_contract, dict)
        and isinstance(alignment_contract.get("core_axis_policy"), dict)
        else alignment_contract
    )
    synonym_dictionary = (
        synonym_policy.get("focal_variable_synonym_dictionary")
        if isinstance(synonym_policy, dict)
        else None
    )
    contract_subhypothesis_id = (
        str(alignment_contract.get("sub_hypothesis_id") or "").strip()
        if isinstance(alignment_contract, dict)
        else ""
    )
    if (
        contract_subhypothesis_id
        and str(prepared.get("status") or "") != "prepared"
        and isinstance(synonym_dictionary, dict)
        and str(synonym_dictionary.get("status") or "")
        in {"ready", "rejected", "unavailable", "not_applicable"}
    ):
        project.setdefault("subhypothesis_alignment_contracts", {})[
            contract_subhypothesis_id
        ] = alignment_contract
        receipt = science_state_manager().commit_v3_project_patch(
            project_id,
            field_updates={
                "subhypothesis_alignment_contracts": project[
                    "subhypothesis_alignment_contracts"
                ],
            },
            artifact_groups=("workflow",),
            expected_version=int(project.get("state_version") or 0),
            operation="PERSIST_ALIGNMENT_CONTRACT_DICTIONARY_STATE",
        )
        project["state_version"] = int(
            receipt.get("state_version") or project.get("state_version") or 0
        )
    committed = commit_prepared_literature_candidate(
        prepared,
        project=project,
        identity_index=identity_index,
    )
    return json.dumps(committed, ensure_ascii=False, indent=2)


def _merge_duplicate_retrieval_evidence(
    existing: dict[str, Any],
    *,
    full_text_excerpt: str,
    open_access_pdf: str,
    full_text_enrichment: dict[str, Any] | None,
    visual_evidence: list[dict[str, Any]] | None,
    extraction_quality: dict[str, Any] | None,
    enrichment_sources: list[str] | None,
    import_context: dict[str, Any] | None,
    alignment_assessment: dict[str, Any] | None,
    evidence_kind: str,
    foundational_bridge_assessment: dict[str, Any] | None,
    paper_genre_assessment: dict[str, Any] | None,
    fulltext_structuring: dict[str, Any] | None,
) -> bool:
    """Safely add richer full text and a per-SH binding to a duplicate.

    PaperGraph remains project-unique, but the same paper can independently
    pass two sub-hypothesis contracts.  The binding stores that second audit
    without overwriting the first branch's alignment verdict.
    """

    changed = False
    incoming_excerpt = str(full_text_excerpt or "").strip()
    existing_excerpt = str(existing.get("full_text_excerpt") or "").strip()
    if len(incoming_excerpt) > len(existing_excerpt):
        existing["full_text_excerpt"] = incoming_excerpt
        if open_access_pdf:
            existing["open_access_pdf"] = str(open_access_pdf)
        if isinstance(full_text_enrichment, dict) and full_text_enrichment:
            existing["full_text_enrichment"] = dict(full_text_enrichment)
        if isinstance(extraction_quality, dict) and extraction_quality:
            existing["extraction_quality"] = dict(extraction_quality)
        existing["full_text_acquisition"] = {
            "status": "AVAILABLE" if len(incoming_excerpt) >= 500 else "ABSTRACT_OR_METADATA_ONLY",
            "available": len(incoming_excerpt) >= 500,
            "excerpt_chars": len(incoming_excerpt),
            "target_policy": "subhypothesis_full_text_required_for_direct_evidence_v1",
        }
        changed = True
    incoming_genre = (
        dict(paper_genre_assessment)
        if isinstance(paper_genre_assessment, dict)
        else {}
    )
    if incoming_genre and existing.get("paper_genre") != incoming_genre:
        existing["paper_genre"] = incoming_genre
        changed = True
    incoming_structuring = (
        dict(fulltext_structuring)
        if isinstance(fulltext_structuring, dict) and fulltext_structuring
        else {}
    )
    if incoming_structuring:
        existing_structuring = (
            dict(existing.get("fulltext_structuring") or {})
            if isinstance(existing.get("fulltext_structuring"), dict)
            else {}
        )
        rank = {
            "": 0,
            "metadata_only_no_fulltext": 0,
            "alignment_not_executed": 1,
            "not_required_deterministic_reject": 1,
            "metadata_plus_fulltext_pending_structuring": 2,
            "structured_deterministic": 3,
            "structured_by_llm": 3,
            "legacy_structured": 3,
        }
        incoming_rank = rank.get(str(incoming_structuring.get("status") or "").lower(), 0)
        existing_rank = rank.get(str(existing_structuring.get("status") or "").lower(), 3 if not existing_structuring else 0)
        if incoming_rank >= existing_rank and existing_structuring != incoming_structuring:
            existing["fulltext_structuring"] = incoming_structuring
            changed = True
    merged_sources = list(dict.fromkeys(
        [
            *[str(item) for item in (existing.get("enrichment_sources") or []) if str(item)],
            *[str(item) for item in (enrichment_sources or []) if str(item)],
        ]
    ))
    if merged_sources != list(existing.get("enrichment_sources") or []):
        existing["enrichment_sources"] = merged_sources
        changed = True

    context = dict(import_context or {})
    alignment = dict(alignment_assessment or {})
    incoming_contract_id = str(
        context.get("research_question_contract_id") or ""
    ).strip()
    incoming_contract_revision = str(
        context.get("research_question_contract_revision") or ""
    ).strip()
    incoming_contract_hash = str(
        context.get("research_question_contract_hash")
        or incoming_contract_revision
        or ""
    ).strip()
    sub_id = str(context.get("sub_hypothesis_id") or "").strip().upper()
    v3_binding_expected = any(
        str(context.get(key) or "").strip()
        for key in (
            "research_question_contract_id",
            "research_question_contract_revision",
            "research_question_contract_hash",
            "research_question_task_id",
            "evidence_slot",
        )
    )
    if v3_binding_expected and not sub_id:
        diagnostics = [
            dict(item)
            for item in (existing.get("v3_unbound_import_diagnostics") or [])
            if isinstance(item, dict)
        ][-49:]
        diagnostic = {
            "reason_code": "EXPLICIT_V3_SUBHYPOTHESIS_PROVENANCE_MISSING",
            "research_question_contract_id": incoming_contract_id,
            "research_question_contract_revision": incoming_contract_revision,
            "research_question_contract_hash": incoming_contract_hash,
            "research_question_task_id": str(
                context.get("research_question_task_id") or ""
            ),
            "target_slot_ids": [
                str(value)
                for value in context.get("target_slot_ids") or (
                    [context.get("evidence_slot") or ""]
                    if context.get("evidence_slot")
                    else []
                )
                if str(value)
            ],
            "evidence_slot": str(context.get("evidence_slot") or ""),
            "source_search_id": str(context.get("search_id") or ""),
            "source_result_index": context.get("result_index"),
            "recorded_at": time.time(),
        }
        if not any(
            all(
                item.get(key) == diagnostic.get(key)
                for key in (
                    "reason_code",
                    "research_question_contract_id",
                    "research_question_contract_revision",
                    "research_question_contract_hash",
                    "source_search_id",
                    "source_result_index",
                )
            )
            for item in diagnostics
        ):
            diagnostics.append(diagnostic)
            existing["v3_unbound_import_diagnostics"] = diagnostics
            changed = True
    incoming_visual = _safe_visual_evidence_units(
        visual_evidence,
        paper_id=str(existing.get("paper_id") or ""),
        sub_hypothesis_id=sub_id,
        source_pdf_url=str(open_access_pdf or existing.get("open_access_pdf") or ""),
    )
    if incoming_visual:
        existing_visual = [
            dict(item)
            for item in (existing.get("visual_evidence") or [])
            if isinstance(item, dict)
        ]
        seen_visual_keys = {
            (
                str(item.get("visual_id") or ""),
                str(item.get("image_sha256") or ""),
                str(item.get("source_locator") or ""),
            )
            for item in existing_visual
        }
        merged_visual = list(existing_visual)
        for unit in incoming_visual:
            key = (
                str(unit.get("visual_id") or ""),
                str(unit.get("image_sha256") or ""),
                str(unit.get("source_locator") or ""),
            )
            if key in seen_visual_keys:
                continue
            seen_visual_keys.add(key)
            merged_visual.append(unit)
        if merged_visual != existing_visual:
            existing["visual_evidence"] = merged_visual
            existing["visual_evidence_summary"] = _visual_evidence_summary(
                merged_visual
            )
            changed = True
    if sub_id:
        existing_bindings = (
            existing.get("subhypothesis_bindings")
            if isinstance(existing.get("subhypothesis_bindings"), list)
            else []
        )
        previous_binding = next(
            (
                item for item in existing_bindings
                if isinstance(item, dict)
                and str(item.get("sub_hypothesis_id") or "").upper() == sub_id
                and (
                    str(item.get("research_question_contract_id") or "")
                    == incoming_contract_id
                    if incoming_contract_id
                    else not str(item.get("research_question_contract_id") or "")
                )
                and (
                    str(item.get("research_question_contract_revision") or "")
                    == incoming_contract_revision
                    if incoming_contract_revision
                    else not str(item.get("research_question_contract_revision") or "")
                )
                and (
                    str(item.get("research_question_contract_hash") or "")
                    == incoming_contract_hash
                    if incoming_contract_hash
                    else not str(item.get("research_question_contract_hash") or "")
                )
            ),
            {},
        )
        if not previous_binding and incoming_contract_id:
            previous_binding = next(
                (
                    item for item in existing_bindings
                    if isinstance(item, dict)
                    and str(item.get("sub_hypothesis_id") or "").upper() == sub_id
                    and not str(item.get("research_question_contract_id") or "")
                ),
                {},
            )
        if (
            not alignment
            and isinstance(previous_binding, dict)
            and str(previous_binding.get("research_question_contract_id") or "")
            == incoming_contract_id
            and str(previous_binding.get("research_question_contract_revision") or "")
            == incoming_contract_revision
            and str(previous_binding.get("research_question_contract_hash") or "")
            == incoming_contract_hash
        ):
            prior_alignment = previous_binding.get("alignment_assessment")
            if isinstance(prior_alignment, dict):
                alignment = dict(prior_alignment)
        binding = {
            "sub_hypothesis_id": sub_id,
            "research_question_contract_id": incoming_contract_id,
            "research_question_contract_revision": incoming_contract_revision,
            "research_question_contract_hash": incoming_contract_hash,
            "research_question_task_id": str(
                context.get("research_question_task_id") or ""
            ),
            "target_slot_ids": [
                str(value)
                for value in context.get("target_slot_ids") or (
                    [context.get("evidence_slot") or ""]
                    if context.get("evidence_slot")
                    else []
                )
                if str(value)
            ],
            "evidence_slot": str(context.get("evidence_slot") or ""),
            "stratified_layer": str(context.get("stratified_layer") or existing.get("stratified_layer") or "L4_regular"),
            "evidence_kind": str(evidence_kind or context.get("evidence_kind") or ""),
            "alignment_assessment": alignment,
            "fulltext_structuring": (
                incoming_structuring
                or dict(existing.get("fulltext_structuring") or {})
            ),
            "corpus_admitted": bool(alignment.get("corpus_admitted")),
            "counts_toward_gate": bool(
                alignment.get("gate_counting_evidence")
            ),
            "foundational_bridge_assessment": dict(foundational_bridge_assessment or {}),
            "source_search_id": str(context.get("search_id") or ""),
            "source_result_index": context.get("result_index"),
            "bound_at": time.time(),
        }
        bindings = [dict(item) for item in existing_bindings if isinstance(item, dict)]
        previous = next(
            (
                item for item in bindings
                if str(item.get("sub_hypothesis_id") or "").upper() == sub_id
                and (
                    str(item.get("research_question_contract_id") or "")
                    == incoming_contract_id
                    if incoming_contract_id
                    else not str(item.get("research_question_contract_id") or "")
                )
                and (
                    str(item.get("research_question_contract_revision") or "")
                    == incoming_contract_revision
                    if incoming_contract_revision
                    else not str(item.get("research_question_contract_revision") or "")
                )
                and (
                    str(item.get("research_question_contract_hash") or "")
                    == incoming_contract_hash
                    if incoming_contract_hash
                    else not str(item.get("research_question_contract_hash") or "")
                )
                and str(item.get("research_question_task_id") or "")
                == str(context.get("research_question_task_id") or "")
            ),
            None,
        )
        if previous is None and incoming_contract_id:
            previous = next(
                (
                    item for item in bindings
                    if str(item.get("sub_hypothesis_id") or "").upper() == sub_id
                    and not str(item.get("research_question_contract_id") or "")
                    and str(item.get("research_question_task_id") or "")
                    == str(context.get("research_question_task_id") or "")
                ),
                None,
            )
        if previous is None:
            bindings.append(binding)
            existing["subhypothesis_bindings"] = bindings
            changed = True
        elif previous is not None and any(
            (
                previous.get("research_question_contract_id")
                != binding["research_question_contract_id"],
                previous.get("research_question_contract_revision")
                != binding["research_question_contract_revision"],
                previous.get("research_question_contract_hash")
                != binding["research_question_contract_hash"],
                previous.get("research_question_task_id")
                != binding["research_question_task_id"],
                previous.get("target_slot_ids")
                != binding["target_slot_ids"],
                previous.get("evidence_slot")
                != binding["evidence_slot"],
                previous.get("alignment_assessment") != binding["alignment_assessment"],
                previous.get("fulltext_structuring")
                != binding["fulltext_structuring"],
                bool(previous.get("corpus_admitted"))
                != binding["corpus_admitted"],
                bool(previous.get("counts_toward_gate"))
                != binding["counts_toward_gate"],
                str(previous.get("stratified_layer") or "")
                != binding["stratified_layer"],
                str(previous.get("evidence_kind") or "")
                != binding["evidence_kind"],
            )
        ):
            previous.update(binding)
            existing["subhypothesis_bindings"] = bindings
            changed = True
    foundation = dict(foundational_bridge_assessment or {})
    if foundation.get("revoked_after_full_text"):
        if existing.get("foundational_bridge_assessment") != foundation:
            existing["foundational_bridge_assessment"] = foundation
            changed = True
    elif foundation.get("bridge_eligible") and not existing.get("foundational_bridge_assessment"):
        existing["foundational_bridge_assessment"] = foundation
        changed = True
    if changed:
        existing["updatedAt"] = time.time()
    return changed


def persist_question_bound_evidence_assertions(
    project: dict[str, Any],
    record: dict[str, Any],
    *,
    evidence_record: dict[str, Any] | None = None,
    contract_ids: set[str] | None = None,
    use_llm: bool | None = None,
    prepared_extraction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh one imported document's V4 LLM-primary evidence projection.

    The importer and the duplicate-enrichment path both call this exact
    function.  It never derives a research-question binding from lexical
    overlap or an historical causal graph: only a current V3 SH contract and
    a document's explicit SH/contract binding can produce assertions.
    """
    try:
        from ._evidence_assertions import (
            extract_record_evidence_assertions,
        )
        from ._evidence_admission import (
            aggregate_task_evidence_admissions,
            apply_evidence_admission,
        )
        from ._evidence_storage import assertion_source_span_ids, compact_record_v4_evidence
        from ._research_question_contract import RESEARCH_QUESTION_CONTRACT_VERSION
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _evidence_assertions import (
            extract_record_evidence_assertions,
        )
        from _evidence_admission import (
            aggregate_task_evidence_admissions,
            apply_evidence_admission,
        )
        from _evidence_storage import assertion_source_span_ids, compact_record_v4_evidence
        from _research_question_contract import RESEARCH_QUESTION_CONTRACT_VERSION
        from _science_execution_policy import resolve_science_execution_policy
    project = project if isinstance(project, dict) else {}
    record = record if isinstance(record, dict) else {}
    contracts = [
        item.get("research_question_contract")
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
        and isinstance(item.get("research_question_contract"), dict)
        and item["research_question_contract"].get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION
    ]
    active_contract_ids = {
        str(contract.get("contract_id") or "")
        for contract in contracts
        if isinstance(contract, dict) and str(contract.get("contract_id") or "")
    }
    scoped_contract_ids = {
        str(contract_id)
        for contract_id in (contract_ids or set())
        if str(contract_id) and str(contract_id) in active_contract_ids
    }
    if contract_ids is None and not scoped_contract_ids:
        scoped_contract_ids = {
            str(binding.get("research_question_contract_id") or "")
            for binding in record.get("subhypothesis_bindings", [])
            if isinstance(binding, dict)
            and str(binding.get("research_question_contract_id") or "") in active_contract_ids
        }
    if contract_ids is not None and not scoped_contract_ids:
        return {
            "schema_version": "record_evidence_assertion_extraction_v4",
            "paper_id": str(record.get("paper_id") or ""),
            "status": "NO_CURRENT_V4_CONTRACT_IN_SCOPE",
            "requested_contract_ids": sorted(
                str(contract_id) for contract_id in contract_ids if str(contract_id)
            ),
            "assertions": [],
            "gap_source_admissions_v4": {},
        }

    # A normalized project materializes paper metadata only.  Before replacing
    # one contract projection, hydrate the old per-paper assertions so IDs for
    # other explicit contracts remain in their registries and paper reference.
    if (
        scoped_contract_ids
        and not isinstance(record.get("evidence_assertions_v4"), list)
        and isinstance(record.get("evidence_storage_v4"), dict)
    ):
        try:
            try:
                from ._project import science_state_manager
            except ImportError:
                from _project import science_state_manager
            hydrated = science_state_manager().get_paper_evidence(
                str(project.get("project_id") or ""),
                str(record.get("paper_id") or ""),
                paper=record,
            )
        except Exception as exc:
            raise RuntimeError(
                "Cannot safely update scoped V4 evidence without its existing "
                "per-paper assertion registry."
            ) from exc
        for key in (
            "evidence_document_v4",
            "source_spans_v6",
            "evidence_assertions_v4",
        ):
            if key in hydrated:
                record[key] = hydrated[key]

    existing_assertions = [
        dict(item)
        for item in record.get("evidence_assertions_v4", [])
        if isinstance(item, dict)
    ]
    existing_admissions = (
        dict(record.get("gap_source_admissions_v4") or {})
        if isinstance(record.get("gap_source_admissions_v4"), dict)
        else {}
    )
    existing_projection = (
        dict(record.get("evidence_projection_v4") or {})
        if isinstance(record.get("evidence_projection_v4"), dict)
        else {}
    )
    existing_slot_supports = [
        dict(item)
        for item in record.get("slot_supports_v4", [])
        if isinstance(item, dict)
    ]
    existing_alignments = (
        {
            str(key): dict(value)
            for key, value in dict(
                record.get("contract_alignment_artifacts") or {}
            ).items()
            if isinstance(value, Mapping)
            and value.get("schema_version") == CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION
        }
        if isinstance(record.get("contract_alignment_artifacts"), dict)
        else {}
    )

    execution_policy = resolve_science_execution_policy(project, use_llm=use_llm)
    protocol_error = _prepared_commit_protocol_error(
        prepared_paper_id=str(record.get("paper_id") or ""),
        document_descriptor=(
            record.get("document_descriptor")
            if isinstance(record.get("document_descriptor"), Mapping)
            else None
        ),
        prepared_evidence_artifact=prepared_extraction,
    )
    if protocol_error:
        reason_codes = [protocol_error]
        apply_evidence_status_dominance(
            record,
            evidence_record,
            status="COMMIT_REJECTED",
            reason_codes=reason_codes,
        )
        return {
            "schema_version": "record_evidence_assertion_extraction_v4",
            "paper_id": str(record.get("paper_id") or ""),
            "status": "COMMIT_REJECTED",
            "protocol_status": "PREPARED_ARTIFACT_PROTOCOL_MISMATCH",
            "reason_codes": reason_codes,
            "assertions": [],
            "gap_source_admissions_v4": {},
        }
    extracted = deepcopy(dict(prepared_extraction))
    incoming_alignments = {
        str(key): dict(value)
        for key, value in dict(
            extracted.get("contract_alignment_artifacts") or {}
        ).items()
        if isinstance(value, Mapping)
    }
    refreshed_scope_keys = {
        (str(contract_id), str(task_id))
        for contract_id, alignment_index in incoming_alignments.items()
        if isinstance(alignment_index.get("task_alignments"), Mapping)
        for task_id in alignment_index["task_alignments"]
        if str(task_id)
    }

    def scope_is_refreshed(item: Mapping[str, Any]) -> bool:
        contract_id = str(item.get("research_question_contract_id") or "")
        task_id = str(item.get("research_question_task_id") or "")
        return (contract_id, task_id) in refreshed_scope_keys

    merged_alignments = dict(existing_alignments)
    for contract_id, alignment_index in incoming_alignments.items():
        previous = dict(merged_alignments.get(contract_id) or {})
        task_alignments = {
            str(task_id): dict(value)
            for task_id, value in dict(previous.get("task_alignments") or {}).items()
            if isinstance(value, Mapping)
        }
        task_alignments.update({
            str(task_id): dict(value)
            for task_id, value in dict(alignment_index.get("task_alignments") or {}).items()
            if isinstance(value, Mapping)
        })
        merged_alignments[contract_id] = {
            "schema_version": CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
            "research_question_contract_id": contract_id,
            "task_alignments": task_alignments,
            "whole_contract_alignment": {"status": "NOT_RUN"},
        }
    record["evidence_document_v4"] = dict(extracted.get("document") or {})
    incoming_proposition_artifact = extracted.get("document_proposition_artifact")
    if isinstance(extracted.get("document_descriptor"), Mapping):
        record["document_descriptor"] = dict(extracted["document_descriptor"])
    record["document_artifact_refs"] = dict(
        extracted.get("document_artifact_refs") or {}
    )
    record["slot_supports_v4"] = [
        *[
            support
            for support in existing_slot_supports
            if not scope_is_refreshed(support)
        ],
        *list(extracted.get("slot_supports") or []),
    ]
    record["contract_alignment_artifacts"] = merged_alignments
    existing_spans = [
        dict(item)
        for item in record.get("source_spans_v6", [])
        if isinstance(item, dict)
    ]
    refreshed_spans = [
        dict(item)
        for item in extracted.get("source_spans", [])
        if isinstance(item, dict)
    ]
    # A scoped repair may see a newer paper document while an unrequested
    # contract still cites spans from the earlier version.  Keep those source
    # units by stable id; the assertion's document version hash remains the
    # authoritative link and no quote is copied into the assertion.
    spans_by_id = {
        str(item.get("source_span_id") or item.get("source_unit_id") or ""): item
        for item in existing_spans
        if str(item.get("source_span_id") or item.get("source_unit_id") or "")
    }
    for span in refreshed_spans:
        span_id = str(span.get("source_span_id") or span.get("source_unit_id") or "")
        if span_id:
            spans_by_id[span_id] = span
    record["source_spans_v6"] = list(spans_by_id.values())
    record["evidence_assertions_v4"] = [
        *[
            assertion
            for assertion in existing_assertions
            if not scope_is_refreshed(assertion)
        ],
        *list(extracted.get("assertions") or []),
    ]
    merged_admissions = dict(existing_admissions)
    for contract_id, value in dict(
        extracted.get("gap_source_admissions_v4") or {}
    ).items():
        if not isinstance(value, Mapping):
            continue
        previous = (
            dict(merged_admissions.get(str(contract_id)) or {})
            if isinstance(merged_admissions.get(str(contract_id)), Mapping)
            else {}
        )
        task_admissions = {
            str(key): dict(item)
            for key, item in dict(previous.get("task_admissions") or {}).items()
            if isinstance(item, Mapping)
        }
        task_admissions.update({
            str(task_id): dict(admission)
            for task_id, admission in dict(value.get("task_admissions") or {}).items()
            if isinstance(admission, Mapping) and str(task_id)
        })
        aggregate = aggregate_task_evidence_admissions(task_admissions)
        merged_admissions[str(contract_id)] = {
            **aggregate,
            "schema_version": "contract_task_admission_index_v1",
            "research_question_contract_id": str(contract_id),
            "research_question_task_id": "",
            "task_admissions": task_admissions,
        }
    record["gap_source_admissions_v4"] = merged_admissions
    apply_evidence_admission(
        record,
        record["gap_source_admissions_v4"],
        evidence_record=evidence_record,
    )
    projection_revisions = (
        dict(existing_projection.get("research_question_contract_revisions") or {})
        if isinstance(existing_projection.get("research_question_contract_revisions"), dict)
        else {}
    )
    projection_revisions.update({
        str(contract.get("contract_id") or ""): str(
            contract.get("contract_revision") or contract.get("declaration_hash") or ""
        )
        for contract in contracts
        if isinstance(contract, dict)
        and str(contract.get("contract_id") or "") in scoped_contract_ids
    })
    extraction_complete = str(extracted.get("extraction_status") or "") == "PROPOSITION_READY"
    record["evidence_projection_v4"] = {
        "schema_version": "evidence_projection_v4",
        "document_version_hash": str((extracted.get("document") or {}).get("document_version_hash") or ""),
        "research_question_contract_revisions": projection_revisions,
        "status": "CURRENT" if extraction_complete else "PENDING",
        "extraction_status": str(extracted.get("extraction_status") or ""),
        "alignment_status_by_contract": {
            f"{contract_id}:{task_id}": str(task_alignment.get("status") or "")
            for contract_id, alignment in record["contract_alignment_artifacts"].items()
            if isinstance(alignment, Mapping)
            for task_id, task_alignment in dict(alignment.get("task_alignments") or {}).items()
            if isinstance(task_alignment, Mapping)
        },
        "document_proposition_cache_status": str(
            extracted.get("document_proposition_cache_status") or ""
        ),
        "effective_policy": execution_policy.to_dict(),
    }
    if isinstance(incoming_proposition_artifact, Mapping):
        record["document_proposition_summary"] = {
            "schema_version": "document_proposition_summary_v2",
            "artifact_id": str(incoming_proposition_artifact.get("artifact_id") or ""),
            "document_version_id": str(
                incoming_proposition_artifact.get("document_version_id") or ""
            ),
            "status": str(incoming_proposition_artifact.get("status") or ""),
            "proposition_count": len(incoming_proposition_artifact.get("propositions") or []),
            "rejected_candidate_count": len(
                incoming_proposition_artifact.get("rejected_candidates") or []
            ),
            "verified_proposition_count": sum(
                isinstance(item, Mapping)
                and item.get("validator_verdict") == "ACCEPTED_SOURCE_BOUND"
                for item in incoming_proposition_artifact.get("propositions", [])
            ),
            "coverage_report": dict(
                incoming_proposition_artifact.get("coverage_report") or {}
            ),
        }
    record["contract_alignment_summaries"] = {
        f"{contract_id}:{task_id}": {
            "schema_version": "contract_alignment_summary_v2",
            "artifact_id": str(alignment.get("artifact_id") or ""),
            "research_question_contract_id": str(
                task_alignment.get("research_question_contract_id") or contract_id
            ),
            "research_question_task_id": str(
                task_id
            ),
            "status": str(task_alignment.get("status") or ""),
            "reason_codes": list(task_alignment.get("reason_codes") or []),
            "assertion_count": len(task_alignment.get("assertions") or []),
            "slot_support_count": len(task_alignment.get("slot_supports") or []),
        }
        for contract_id, alignment in record["contract_alignment_artifacts"].items()
        if isinstance(alignment, Mapping)
        for task_id, task_alignment in dict(alignment.get("task_alignments") or {}).items()
        if isinstance(task_alignment, Mapping)
    }
    enrichment = (
        dict(record.get("full_text_enrichment") or {})
        if isinstance(record.get("full_text_enrichment"), Mapping)
        else {}
    )
    if enrichment:
        enrichment["document_artifact_refs"] = dict(
            record.get("document_artifact_refs") or {}
        )
        enrichment["artifact_counts"] = {
            "canonical_text_chars": len(str(enrichment.get("canonical_text") or "")),
            "raw_layout_page_count": len(enrichment.get("raw_layout_pages") or []),
            "source_fragment_count": len(enrichment.get("fragment_registry") or []),
            "paragraph_count": len(enrichment.get("paragraphs") or []),
            "source_span_count": len(enrichment.get("evidence_spans") or []),
            "llm_chunk_count": len(enrichment.get("llm_chunks") or []),
        }
        for field in (
            "canonical_text",
            "raw_layout_pages",
            "fragment_registry",
            "paragraphs",
            "sections",
            "llm_chunks",
            "evidence_spans",
            "coverage_manifest",
        ):
            enrichment.pop(field, None)
        record["full_text_enrichment"] = enrichment
    if not extraction_complete:
        dominance_status = (
            "ALIGNMENT_PENDING" if extraction_complete else str(
                extracted.get("extraction_status") or "PROPOSITION_PENDING"
            )
        )
        dominance_reasons = list(extracted.get("reason_codes") or [])
        if extraction_complete and not dominance_reasons:
            dominance_reasons = list(dict.fromkeys(
                str(reason)
                for alignment in record["contract_alignment_artifacts"].values()
                if isinstance(alignment, Mapping)
                for reason in alignment.get("reason_codes", [])
                if str(reason)
            ))
        apply_evidence_status_dominance(
            record,
            evidence_record,
            status=dominance_status,
            reason_codes=dominance_reasons,
        )
    # The old scalar admission is ambiguous across SHs and never qualifies a
    # V3 candidate, so it is deliberately removed rather than translated.
    record.pop("gap_source_admission", None)
    record.pop("document_sections_v5", None)
    record.pop("scientific_propositions", None)
    record.pop("document_proposition_artifact", None)
    record.pop("contract_alignment_artifacts", None)
    compact_record_v4_evidence(record)
    if isinstance(evidence_record, dict):
        evidence_record["source_span_refs"] = assertion_source_span_ids(
            record["evidence_assertions_v4"]
        )
        evidence_record["evidence_assertion_ids"] = [
            str(assertion.get("assertion_id") or "")
            for assertion in record["evidence_assertions_v4"]
            if isinstance(assertion, dict)
        ]
        evidence_record["gap_source_admissions_v4"] = dict(record["gap_source_admissions_v4"])
        evidence_record["slot_supports_v4"] = list(record["slot_supports_v4"])
        evidence_record["evidence_projection_v4"] = dict(record["evidence_projection_v4"])
        evidence_record.pop("gap_source_admission", None)
    return extracted


def reassess_v3_imported_candidates_for_contract(
    project_id: str,
    *,
    sub_hypothesis_ids: set[str] | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Re-evaluate existing V3 records that were imported without alignment.

    This is an artifact repair, not a fallback retrieval route: it reuses the
    existing metadata/full text, binds each record to its declared V3 contract,
    refreshes source-bound assertions, and records a revision audit.
    """

    try:
        from ._project import load_project, science_state_manager
        from ._evidence_assertions import (
            build_document_record_v4,
            extract_record_evidence_assertions,
        )
        from ._evidence_preparation_store import (
            load_document_proposition_artifact,
            persist_document_proposition_artifact,
        )
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _project import load_project, science_state_manager
        from _evidence_assertions import (
            build_document_record_v4,
            extract_record_evidence_assertions,
        )
        from _evidence_preparation_store import (
            load_document_proposition_artifact,
            persist_document_proposition_artifact,
        )
        from _science_execution_policy import resolve_science_execution_policy

    project = load_project(project_id)
    state_manager = science_state_manager()
    execution_policy = resolve_science_execution_policy(project, use_llm=use_llm)
    requested_ids = {str(value) for value in (sub_hypothesis_ids or set()) if str(value)}
    contracts_by_sub_id = {
        str(item.get("id") or item.get("sub_hypothesis_id") or ""): item.get("research_question_contract")
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
        and isinstance(item.get("research_question_contract"), dict)
        and str((item.get("research_question_contract") or {}).get("schema_version") or "") == "research_question_contract_v3"
    }
    contract_ids_by_sub_id = {
        sub_id: str(contract.get("contract_id") or "")
        for sub_id, contract in contracts_by_sub_id.items()
        if isinstance(contract, dict) and str(contract.get("contract_id") or "")
    }
    revised: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    evidence_by_paper = {
        str(item.get("paper_id") or ""): item
        for item in project.get("evidence", [])
        if isinstance(item, dict) and str(item.get("paper_id") or "")
    }
    papergraph = project.get("papergraph") if isinstance(project.get("papergraph"), list) else []
    for record_index, record in enumerate(papergraph):
        if not isinstance(record, dict):
            continue
        record_binding_normalized = False
        bindings = (
            record.get("subhypothesis_bindings")
            if isinstance(record.get("subhypothesis_bindings"), list)
            else []
        )
        explicit_sub_ids = {
            str(binding.get("sub_hypothesis_id") or "")
            for binding in bindings
            if isinstance(binding, dict) and str(binding.get("sub_hypothesis_id") or "")
        }
        scalar_sub_id = str(
            record.get("sub_hypothesis_id")
            or (record.get("import_context") or {}).get("sub_hypothesis_id")
            or ""
        )
        if scalar_sub_id and (not requested_ids or scalar_sub_id in requested_ids):
            explicit_sub_ids.add(scalar_sub_id)
            # Some records produced during the import-contract propagation
            # defect carry a direct V3 SH id but no binding list yet. That is
            # explicit provenance, so normalize it into the binding form used
            # by all current V3 consumers; do not infer any additional SH.
            if not any(
                isinstance(binding, dict)
                and str(binding.get("sub_hypothesis_id") or "") == scalar_sub_id
                for binding in bindings
            ):
                bindings.append({
                    "sub_hypothesis_id": scalar_sub_id,
                    "research_question_contract_id": str(
                        record.get("research_question_contract_id")
                        or (record.get("import_context") or {}).get(
                            "research_question_contract_id"
                        )
                        or ""
                    ),
                    "research_question_contract_revision": str(
                        (record.get("import_context") or {}).get(
                            "research_question_contract_revision"
                        )
                        or ""
                    ),
                    "research_question_contract_hash": str(
                        (record.get("import_context") or {}).get(
                            "research_question_contract_hash"
                        )
                        or ""
                    ),
                    "alignment_assessment": dict(
                        record.get("alignment_assessment") or {}
                    ),
                    "fulltext_structuring": dict(
                        record.get("fulltext_structuring") or {}
                    ),
                    "binding_origin": "explicit_v3_import_provenance_repair",
                })
                record["subhypothesis_bindings"] = bindings
                record_binding_normalized = True
        target_sub_ids = sorted(
            sub_id
            for sub_id in explicit_sub_ids
            if sub_id and (not requested_ids or sub_id in requested_ids)
        )
        if not target_sub_ids:
            continue
        evidence_record = evidence_by_paper.get(str(record.get("paper_id") or ""))
        reassessed_bindings = False
        for sub_id in target_sub_ids:
            contract = contracts_by_sub_id.get(sub_id)
            if not isinstance(contract, dict):
                skipped.append({
                    "paper_id": str(record.get("paper_id") or ""),
                    "sub_hypothesis_id": sub_id,
                    "reason": "missing_current_v3_contract",
                })
                continue
            current_contract_id = str(contract.get("contract_id") or "")
            current_contract_revision = str(
                contract.get("contract_revision") or contract.get("declaration_hash") or ""
            )
            current_contract_hash = str(
                contract.get("declaration_hash") or contract.get("contract_revision") or ""
            )
            binding = next(
                (
                    item for item in bindings
                    if isinstance(item, dict)
                    and str(item.get("sub_hypothesis_id") or "") == sub_id
                    and str(item.get("research_question_contract_id") or "")
                    == current_contract_id
                    and str(item.get("research_question_contract_revision") or "")
                    == current_contract_revision
                    and str(item.get("research_question_contract_hash") or "")
                    == current_contract_hash
                ),
                {},
            )
            if not binding:
                binding = next(
                    (
                        item for item in bindings
                        if isinstance(item, dict)
                        and str(item.get("sub_hypothesis_id") or "") == sub_id
                        and not str(item.get("research_question_contract_id") or "")
                    ),
                    {},
                )
            if not binding:
                prior_revision_binding = next(
                    (
                        item for item in bindings
                        if isinstance(item, dict)
                        and str(item.get("sub_hypothesis_id") or "") == sub_id
                    ),
                    {},
                )
                binding = {
                    "sub_hypothesis_id": sub_id,
                    "research_question_contract_id": current_contract_id,
                    "research_question_contract_revision": current_contract_revision,
                    "research_question_contract_hash": current_contract_hash,
                    "stratified_layer": str(
                        prior_revision_binding.get("stratified_layer") or ""
                    ),
                    "evidence_kind": str(
                        prior_revision_binding.get("evidence_kind") or ""
                    ),
                    "fulltext_structuring": {
                        "status": "alignment_not_executed",
                        "eligible_for_evidence_admission": False,
                        "reason": "current_v3_contract_requires_independent_reassessment",
                    },
                    "binding_origin": "v3_contract_revision_reassessment",
                    "supersedes_contract_id": str(
                        prior_revision_binding.get(
                            "research_question_contract_id"
                        )
                        or ""
                    ),
                    "supersedes_contract_revision": str(
                        prior_revision_binding.get(
                            "research_question_contract_revision"
                        )
                        or ""
                    ),
                    "bound_at": time.time(),
                }
                bindings.append(binding)
                record["subhypothesis_bindings"] = bindings
            binding = binding if isinstance(binding, dict) else {}
            alignment = (
                binding.get("alignment_assessment")
                if isinstance(binding.get("alignment_assessment"), dict)
                else {}
            )
            structuring = (
                binding.get("fulltext_structuring")
                if isinstance(binding.get("fulltext_structuring"), dict)
                else {}
            )
            needs_reassessment = (
                not alignment
                or not str(alignment.get("contract_hash") or alignment.get("contract_revision") or "")
                or str(alignment.get("contract_hash") or alignment.get("contract_revision") or "")
                != current_contract_hash
                or str(structuring.get("status") or "") == "alignment_not_executed"
            )
            if not needs_reassessment:
                continue
            previous = {
                "alignment_assessment": dict(alignment),
                "fulltext_structuring": dict(structuring),
            }
            assessment = {
                "schema_version": "v3_retrieval_reassessment_required_v1",
                "assessment_stage": "v3_imported_artifact_retrieval_required",
                "contract_id": current_contract_id,
                "research_question_contract_id": current_contract_id,
                "research_question_contract_revision": current_contract_revision,
                "research_question_contract_hash": current_contract_hash,
                "contract_hash": current_contract_hash,
                "decision": "RETRIEVAL_REQUIRED",
                "reason_code": "V3_TASK_LOCAL_RETRIEVAL_REQUIRED",
                "reason_codes": ["V3_TASK_LOCAL_RETRIEVAL_REQUIRED"],
                "reason": (
                    "Existing records are not reclassified through historical causal alignment. "
                    "Run the current V3 task-local retrieval plan to establish source-bound "
                    "admission for this contract revision."
                ),
                "import_eligible": False,
                "corpus_admitted": False,
                "gate_counting_evidence": False,
                "core_eligible": False,
                "eligible_slot_ids": [],
                "slot_eligibility_status": "RETRIEVAL_REQUIRED",
                "v1_causal_alignment_applied": False,
            }
            assessed_structuring = {
                **structuring,
                "schema_version": "fulltext_structuring_v1",
                "status": "alignment_not_executed",
                "eligible_for_evidence_admission": False,
                "reason": "v3_task_local_retrieval_required_for_current_contract",
                "role": "retrieval_required",
                "alignment_status": "NOT_EXECUTED",
            }
            for current_binding in bindings:
                if (
                    not isinstance(current_binding, dict)
                    or str(current_binding.get("sub_hypothesis_id") or "") != sub_id
                    or str(current_binding.get("research_question_contract_id") or "")
                    != current_contract_id
                    or str(current_binding.get("research_question_contract_revision") or "")
                    != current_contract_revision
                    or str(current_binding.get("research_question_contract_hash") or "")
                    != current_contract_hash
                ):
                    continue
                current_binding["alignment_assessment"] = dict(assessment)
                current_binding["fulltext_structuring"] = dict(assessed_structuring)
                current_binding["corpus_admitted"] = bool(
                    assessment.get("corpus_admitted")
                )
                current_binding["counts_toward_gate"] = bool(
                    assessment.get("gate_counting_evidence")
                )
                current_binding["research_question_contract_id"] = str(contract.get("contract_id") or "")
                current_binding["research_question_contract_revision"] = str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                )
                current_binding["research_question_contract_hash"] = current_contract_hash
            log_event(
                "SCIENCE",
                "v3_imported_candidate_retrieval_required",
                project_id=project_id,
                paper_id=str(record.get("paper_id") or ""),
                sub_hypothesis_id=sub_id,
                research_question_contract_id=str(contract.get("contract_id") or ""),
                contract_hash=assessment["contract_hash"],
                import_eligible=False,
                corpus_admitted=False,
            )
            revision = {
                "schema_version": "v3_candidate_reassessment_v1",
                "reason_code": "V3_TASK_LOCAL_RETRIEVAL_REQUIRED",
                "sub_hypothesis_id": sub_id,
                "research_question_contract_id": str(contract.get("contract_id") or ""),
                "contract_hash": assessment["contract_hash"],
                "previous": previous,
                "result": {
                    "import_eligible": bool(assessment.get("import_eligible")),
                    "corpus_admitted": bool(assessment.get("corpus_admitted")),
                    "gate_counting_evidence": bool(assessment.get("gate_counting_evidence")),
                    "verdict": str(assessment.get("decision") or ""),
                },
                "reassessed_at": time.time(),
            }
            record.setdefault("v3_reassessment_history", []).append(revision)
            revised.append({
                "paper_id": str(record.get("paper_id") or ""),
                "sub_hypothesis_id": sub_id,
                **revision["result"],
            })
            reassessed_bindings = True
        if reassessed_bindings or record_binding_normalized:
            scoped_contract_ids = {
                contract_ids_by_sub_id[sub_id]
                for sub_id in target_sub_ids
                if sub_id in contract_ids_by_sub_id
            }
            descriptor = (
                record.get("document_descriptor")
                if isinstance(record.get("document_descriptor"), Mapping)
                else {}
            )
            document = build_document_record_v4(record)
            cached_bundle = load_document_proposition_artifact(
                project_id=project_id,
                paper_id=str(record.get("paper_id") or ""),
                document=document,
            )
            if not descriptor or not isinstance(cached_bundle, Mapping):
                skipped.append({
                    "paper_id": str(record.get("paper_id") or ""),
                    "sub_hypothesis_ids": target_sub_ids,
                    "reason": "PREPARED_DOCUMENT_PROPOSITION_ARTIFACT_REQUIRED",
                })
                apply_evidence_status_dominance(
                    record,
                    evidence_record,
                    status="ALIGNMENT_PENDING",
                    reason_codes=["PREPARED_DOCUMENT_PROPOSITION_ARTIFACT_REQUIRED"],
                )
                continue
            record["document_proposition_artifact"] = dict(
                cached_bundle.get("document_proposition_artifact") or {}
            )
            record["document_sections_v5"] = list(
                cached_bundle.get("document_sections") or []
            )
            record["source_spans_v6"] = list(cached_bundle.get("source_spans") or [])
            prepared_reassessment = extract_record_evidence_assertions(
                record,
                [
                    contract for contract in contracts_by_sub_id.values()
                    if isinstance(contract, dict)
                ],
                policy=execution_policy,
                contract_ids=scoped_contract_ids,
            )
            prepared_reassessment["document_descriptor"] = dict(descriptor)
            prepared_reassessment["document_artifact_refs"] = dict(
                cached_bundle.get("artifact_refs") or {}
            )
            proposition_artifact = prepared_reassessment.get(
                "document_proposition_artifact"
            )
            if isinstance(proposition_artifact, Mapping):
                artifact_manifest = persist_document_proposition_artifact(
                    project_id=project_id,
                    paper_id=str(record.get("paper_id") or ""),
                    artifact=proposition_artifact,
                    document_descriptor=descriptor,
                    document_sections=list(
                        prepared_reassessment.get("document_sections") or []
                    ),
                    source_spans=list(prepared_reassessment.get("source_spans") or []),
                    contract_alignment_artifacts=dict(
                        prepared_reassessment.get("contract_alignment_artifacts") or {}
                    ),
                )
                prepared_reassessment["document_artifact_refs"] = dict(
                    artifact_manifest.get("artifact_refs") or {}
                )
                prepared_reassessment["document_descriptor"] = dict(
                    artifact_manifest.get("document_descriptor") or descriptor
                )
            persist_question_bound_evidence_assertions(
                project,
                record,
                evidence_record=evidence_record,
                contract_ids=scoped_contract_ids,
                use_llm=use_llm,
                prepared_extraction=prepared_reassessment,
            )
            receipt = state_manager.commit_prepared_candidate(
                project_id,
                paper=record,
                evidence_record=evidence_record,
                expected_version=int(project.get("state_version") or 0),
            )
            project["state_version"] = int(receipt.get("state_version") or 0)
            project["state_context"] = {
                "store_id": str(project.get("state_store_id") or ""),
                "loaded_version": int(project["state_version"]),
            }
            if isinstance(receipt.get("paper"), dict):
                papergraph[record_index] = receipt["paper"]
            if isinstance(evidence_record, dict) and isinstance(
                receipt.get("evidence_record"), dict
            ):
                evidence_record.clear()
                evidence_record.update(receipt["evidence_record"])
        if record_binding_normalized:
            revised.append({
                "paper_id": str(record.get("paper_id") or ""),
                "sub_hypothesis_id": scalar_sub_id,
                "binding_normalized": True,
            })
    if revised:
        project.setdefault("v3_evidence_reassessment", []).append({
            "schema_version": "v3_candidate_reassessment_batch_v1",
            "project_id": project_id,
            "reassessed_at": time.time(),
            "records": revised,
        })
        project["updatedAt"] = time.time()
        patch_receipt = state_manager.commit_v3_project_patch(
            project_id,
            field_updates={
                "v3_evidence_reassessment": project["v3_evidence_reassessment"],
            },
            artifact_groups=("papers",),
            expected_version=int(project.get("state_version") or 0),
            operation="PERSIST_V3_EVIDENCE_REASSESSMENT_AUDIT",
        )
        project["state_version"] = int(
            patch_receipt.get("state_version") or project.get("state_version") or 0
        )
    return {
        "schema_version": "v3_candidate_reassessment_result_v1",
        "project_id": project_id,
        "reassessed_count": len(revised),
        "reassessed_records": revised,
        "skipped_records": skipped,
        "network_retrieval_performed": False,
    }

def import_papergraph_record(
    project_id: str,
    title: str,
    citation: str,
    authors: list[str] | None = None,
    year: str = "",
    venue: str = "",
    provider: str = "manual",
    source_type: str = "metadata",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    openalex_id: str = "",
    url: str = "",
    abstract: str = "",
    full_text_excerpt: str = "",
    open_access_pdf: str = "",
    full_text_enrichment: dict[str, Any] | None = None,
    visual_evidence: list[dict[str, Any]] | None = None,
    conclusion: str = "",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    method: str = "",
    scenario: str = "",
    benchmark: str = "",
    contribution: str = "",
    limitation: str = "",
    extraction_quality: dict[str, Any] | None = None,
    enrichment_sources: list[str] | None = None,
    gap_signals: list[dict[str, Any]] | None = None,
    causal_chains: list[dict[str, Any]] | None = None,
    import_context: dict[str, Any] | None = None,
    retrieval_query: str = "",
    domain_relevance: dict[str, Any] | None = None,
    domain_review: dict[str, Any] | None = None,
    domain_gate: dict[str, Any] | None = None,
    domain_override: dict[str, Any] | None = None,
    research_role: str = "",
    research_role_assessment: dict[str, Any] | None = None,
    subhypothesis_bindings: list[dict[str, Any]] | None = None,
    research_question_card_version: str = "",
    alignment_assessment: dict[str, Any] | None = None,
    evidence_kind: str = "",
    alignment_override: dict[str, Any] | None = None,
    foundational_bridge_assessment: dict[str, Any] | None = None,
    paper_genre_assessment: dict[str, Any] | None = None,
    paper_domain_assessment: dict[str, Any] | None = None,
    paper_classification: dict[str, Any] | None = None,
    fulltext_structuring: dict[str, Any] | None = None,
    provider_provenance: dict[str, Any] | None = None,
    external_ids: dict[str, Any] | None = None,
    citation_metrics: dict[str, Any] | None = None,
    prepared_paper_id: str = "",
    document_descriptor: dict[str, Any] | None = None,
    prepared_evidence_artifact: dict[str, Any] | None = None,
    *,
    use_llm: bool | None = None,
    project: dict[str, Any] | None = None,
    identity_index: dict[str, dict[str, Any]] | None = None,
    save: bool = True,
) -> str:
    try:
        from ._gap_detection import extract_gap_signals_from_text, normalize_gap_signals
        from ._literature_retrieval_foundation import canonical_paper_identity
        from ._models import PaperEvidence, PaperGraphRecord
        from ._project import load_project, load_search, save_project
        from ._research_alignment import classify_causal_role
        from ._utils import find_by_id, first_sentences, is_unknown_value, new_id, normalize_space, repair_unknown_field
    except ImportError:
        from _gap_detection import extract_gap_signals_from_text, normalize_gap_signals
        from _literature_retrieval_foundation import canonical_paper_identity
        from _models import PaperEvidence, PaperGraphRecord
        from _project import load_project, load_search, save_project
        from _research_alignment import classify_causal_role
        from _utils import find_by_id, first_sentences, is_unknown_value, new_id, normalize_space, repair_unknown_field
    doi = normalize_optional_identifier(doi)
    arxiv_id = normalize_optional_identifier(arxiv_id)
    semantic_scholar_id = normalize_optional_identifier(semantic_scholar_id)
    openalex_id = normalize_optional_identifier(openalex_id)
    url = normalize_optional_identifier(url)
    external_ids = _normalize_external_identifiers(external_ids)
    project = project if isinstance(project, dict) else load_project(project_id)
    protocol_error = _prepared_commit_protocol_error(
        prepared_paper_id=prepared_paper_id,
        document_descriptor=document_descriptor,
        prepared_evidence_artifact=prepared_evidence_artifact,
    )
    if protocol_error:
        log_event(
            "WARN",
            "candidate_commit_rejected",
            project_id=project_id,
            paper_id=str(prepared_paper_id or ""),
            protocol_status="PREPARED_ARTIFACT_PROTOCOL_MISMATCH",
            reason_codes=[protocol_error],
        )
        return json.dumps(
            {
                "status": "commit_rejected",
                "paper_id": str(prepared_paper_id or ""),
                "protocol_status": "PREPARED_ARTIFACT_PROTOCOL_MISMATCH",
                "reason_codes": [protocol_error],
            },
            ensure_ascii=False,
            indent=2,
        )
    # A current research-question project owns its evidence projection through
    # Document → SourceSpan → EvidenceAssertion.  The import transaction must
    # not simultaneously manufacture legacy causal chains or lexical gap
    # signals, even as unused metadata: mixed artifacts make later audits
    # ambiguous and invite accidental reuse by a stale consumer.
    current_subhypotheses = [
        item for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
    ]
    # A declaration is not yet a usable binding.  Materialise and validate the
    # current V3 contracts before document import, so every resulting
    # EvidenceAssertion can carry an exact contract id and revision.  This is
    # construction from the explicit V3 declaration, never conversion from a
    # legacy causal SH.
    if current_subhypotheses:
        try:
            try:
                from ._subhypothesis_annotation import annotate_project_subhypotheses
            except ImportError:
                from _subhypothesis_annotation import annotate_project_subhypotheses
            project["subhypothesis_annotation_summary"] = (
                annotate_project_subhypotheses(project)
            )
            current_subhypotheses = [
                item for item in project.get("sub_hypotheses", [])
                if isinstance(item, dict)
            ]
        except (TypeError, ValueError) as exc:
            return json.dumps(
                {
                    "schema_version": "research_question_evidence_v3",
                    "project_id": project_id,
                    "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                    "imported": False,
                    "legacy_causal_artifacts_accepted": False,
                    "reason": "V3_RESEARCH_QUESTION_CONTRACT_CONSTRUCTION_FAILED",
                    "detail": str(exc),
                    "next_step": (
                        "Correct the explicit ResearchQuestionContractV3 "
                        "declaration before importing evidence."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
    research_question_evidence_v3 = bool(current_subhypotheses) and all(
        isinstance(item.get("research_question_contract"), dict)
        and item["research_question_contract"].get("schema_version")
        == "research_question_contract_v3"
        and item.get("evidence_pipeline_schema")
        == "research_question_evidence_v3"
        for item in current_subhypotheses
    )
    # V3 is a hard boundary, not an adapter.  An old causal SH must be
    # re-decomposed before it can accept new literature; otherwise this
    # importer would recreate causal-chain and lexical-gap side channels while
    # the rest of the project is being upgraded.  A project with no SH is
    # permitted to retain an unlinked source document, but still uses the V3
    # document/source-span projection rather than the retired projection.
    if current_subhypotheses and not research_question_evidence_v3:
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}")
            for index, item in enumerate(current_subhypotheses)
        ]
        for item in current_subhypotheses:
            item["evidence_pipeline_schema"] = "STALE_SCHEMA"
            item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
            item["hypothesis_annotation_status"] = (
                "research_question_contract_v3_required"
            )
        project["research_question_cutover_status"] = (
            "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        )
        project["updatedAt"] = time.time()
        if save:
            save_project(project)
        return json.dumps(
            {
                "schema_version": "research_question_evidence_v3",
                "project_id": project_id,
                "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                "imported": False,
                "stale_sub_hypothesis_ids": stale_ids,
                "legacy_causal_artifacts_accepted": False,
                "next_step": (
                    "Re-decompose the project into explicit "
                    "ResearchQuestionContractV3 sub-hypotheses before "
                    "importing evidence."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    # From here down, both a complete V3 project and an empty project use only
    # the V3 source projection.  Empty projects retain documents as unlinked
    # evidence and never fall back to causal-chain/gap-signal extraction.
    research_question_evidence_v3 = True
    identity_candidate = {
        "title": title,
        "citation": citation,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": semantic_scholar_id,
        "openalex_id": openalex_id,
        "url": url,
        "external_ids": dict(external_ids or {}),
    }
    paper_identity = canonical_paper_identity(identity_candidate)
    pmid = _first_optional_identifier(
        (external_ids or {}).get("pmid"),
        (external_ids or {}).get("pubmed"),
    )
    unique_key = paper_unique_key(
        title=title,
        citation=citation,
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_scholar_id,
        url=url,
        openalex_id=openalex_id,
        pmid=pmid,
    )
    duplicate = find_by_id(project.get("papergraph", []), "unique_key", unique_key)
    if duplicate is None:
        duplicate = find_project_paper_by_identity(
            identity_index,
            identity_candidate,
            project=project,
        )
    if duplicate is None:
        incoming_aliases = set(paper_identity.get("matching_aliases") or ())
        if incoming_aliases:
            for existing in project.get("papergraph", []):
                if not isinstance(existing, dict):
                    continue
                existing_identity = canonical_paper_identity(existing)
                if incoming_aliases & set(existing_identity.get("matching_aliases") or ()):
                    duplicate = existing
                    break
    if duplicate is not None:
        duplicate_updated = _merge_duplicate_retrieval_evidence(
            duplicate,
            full_text_excerpt=full_text_excerpt,
            open_access_pdf=open_access_pdf,
            full_text_enrichment=full_text_enrichment,
            visual_evidence=visual_evidence,
            extraction_quality=extraction_quality,
            enrichment_sources=enrichment_sources,
            import_context=import_context,
            alignment_assessment=alignment_assessment,
            evidence_kind=evidence_kind,
            foundational_bridge_assessment=foundational_bridge_assessment,
            paper_genre_assessment=paper_genre_assessment,
            fulltext_structuring=fulltext_structuring,
        )
        if isinstance(paper_domain_assessment, dict) and paper_domain_assessment:
            duplicate["paper_domain_assessment"] = dict(paper_domain_assessment)
            duplicate_updated = True
        if isinstance(paper_classification, dict) and paper_classification:
            duplicate["paper_classification"] = dict(paper_classification)
            duplicate_updated = True
        if isinstance(document_descriptor, dict) and document_descriptor:
            duplicate["document_descriptor"] = deepcopy(document_descriptor)
            duplicate_updated = True
        if duplicate_updated or "evidence_assertions_v4" not in duplicate:
            duplicate_evidence = next(
                (
                    item for item in project.get("evidence", [])
                    if isinstance(item, dict)
                    and str(item.get("paper_id") or "") == str(duplicate.get("paper_id") or "")
                ),
                None,
            )
            before_projection = (
                duplicate.get("source_spans_v6"),
                duplicate.get("evidence_assertions_v4"),
                duplicate.get("gap_source_admissions_v4"),
            )
            persist_question_bound_evidence_assertions(
                project,
                duplicate,
                evidence_record=duplicate_evidence if isinstance(duplicate_evidence, dict) else None,
                use_llm=use_llm,
                prepared_extraction=prepared_evidence_artifact,
            )
            duplicate_updated = duplicate_updated or before_projection != (
                duplicate.get("source_spans_v6"),
                duplicate.get("evidence_assertions_v4"),
                duplicate.get("gap_source_admissions_v4"),
            )
        if identity_index is not None:
            register_project_paper_identity(identity_index, duplicate)
        if duplicate_updated and save:
            save_project(project)
        log_event("SCIENCE", "paper_duplicate", project_id=project_id, paper_id=duplicate.get("paper_id"), unique_key=unique_key)
        return json.dumps(
            {
                "status": "duplicate",
                "unique_key": unique_key,
                "existing_record": duplicate,
                "existing_record_updated": duplicate_updated,
            },
            ensure_ascii=False,
            indent=2,
        )

    # Title-based fuzzy dedup: catch same-paper imports from different providers/identifiers
    normalized_new_title = normalize_space(title).lower()
    if normalized_new_title and len(normalized_new_title) >= 10:
        new_title_tokens = set(re.findall(r"[a-z0-9]+", normalized_new_title))
        for existing in project.get("papergraph", []):
            if not isinstance(existing, dict):
                continue
            # Compare against both LLM-rewritten title and original search title
            existing_titles_to_check = [
                normalize_space(str(existing.get("title") or "")).lower(),
                normalize_space(str(existing.get("original_search_title") or "")).lower(),
            ]
            for existing_title in existing_titles_to_check:
                if not existing_title or len(existing_title) < 10:
                    continue
                existing_tokens = set(re.findall(r"[a-z0-9]+", existing_title))
                if not new_title_tokens or not existing_tokens:
                    continue
                intersection = new_title_tokens & existing_tokens
                union = new_title_tokens | existing_tokens
                jaccard = len(intersection) / max(1, len(union))
                if jaccard >= 0.75:
                    duplicate_updated = _merge_duplicate_retrieval_evidence(
                        existing,
                        full_text_excerpt=full_text_excerpt,
                        open_access_pdf=open_access_pdf,
                        full_text_enrichment=full_text_enrichment,
                        visual_evidence=visual_evidence,
                        extraction_quality=extraction_quality,
                        enrichment_sources=enrichment_sources,
                        import_context=import_context,
                        alignment_assessment=alignment_assessment,
                        evidence_kind=evidence_kind,
                        foundational_bridge_assessment=foundational_bridge_assessment,
                        paper_genre_assessment=paper_genre_assessment,
                        fulltext_structuring=fulltext_structuring,
                    )
                    if isinstance(paper_domain_assessment, dict) and paper_domain_assessment:
                        existing["paper_domain_assessment"] = dict(paper_domain_assessment)
                        duplicate_updated = True
                    if isinstance(paper_classification, dict) and paper_classification:
                        existing["paper_classification"] = dict(paper_classification)
                        duplicate_updated = True
                    if isinstance(document_descriptor, dict) and document_descriptor:
                        existing["document_descriptor"] = deepcopy(document_descriptor)
                        duplicate_updated = True
                    if duplicate_updated or "evidence_assertions_v4" not in existing:
                        duplicate_evidence = next(
                            (
                                item for item in project.get("evidence", [])
                                if isinstance(item, dict)
                                and str(item.get("paper_id") or "") == str(existing.get("paper_id") or "")
                            ),
                            None,
                        )
                        before_projection = (
                            existing.get("source_spans_v6"),
                            existing.get("evidence_assertions_v4"),
                            existing.get("gap_source_admissions_v4"),
                        )
                        persist_question_bound_evidence_assertions(
                            project,
                            existing,
                            evidence_record=duplicate_evidence if isinstance(duplicate_evidence, dict) else None,
                            use_llm=use_llm,
                            prepared_extraction=prepared_evidence_artifact,
                        )
                        duplicate_updated = duplicate_updated or before_projection != (
                            existing.get("source_spans_v6"),
                            existing.get("evidence_assertions_v4"),
                            existing.get("gap_source_admissions_v4"),
                        )
                    if identity_index is not None:
                        register_project_paper_identity(identity_index, existing)
                    if duplicate_updated and save:
                        save_project(project)
                    log_event(
                        "SCIENCE",
                        "paper_fuzzy_title_duplicate",
                        project_id=project_id,
                        paper_id=existing.get("paper_id"),
                        jaccard=round(jaccard, 3),
                        new_title=title[:80],
                        existing_title=existing_title[:80],
                    )
                    return json.dumps(
                        {
                            "status": "duplicate",
                            "reason": "fuzzy_title_match",
                            "jaccard": round(jaccard, 3),
                            "unique_key": unique_key,
                            "existing_record": existing,
                            "existing_record_updated": duplicate_updated,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )

    # Allocate the stable paper foreign key before extraction so every gap
    # signal and causal source unit can retain provenance from its first
    # materialization.  Duplicate exits above do not consume persistent state.
    record_paper_id = str(prepared_paper_id or "").strip() or new_id("paper")
    normalized_import_context = {
        key: value
        for key, value in dict(import_context or {}).items()
        if value not in (None, "")
    }
    retrieval_branch = str(
        normalized_import_context.get("query_branch")
        or normalized_import_context.get("retrieval_branch")
        or ""
    ).strip()
    source_sub_hypothesis_id = str(
        normalized_import_context.get("sub_hypothesis_id") or ""
    ).strip().upper()
    v3_binding_expected = any(
        str(normalized_import_context.get(key) or "").strip()
        for key in (
            "research_question_contract_id",
            "research_question_contract_revision",
            "research_question_contract_hash",
            "research_question_task_id",
            "evidence_slot",
        )
    )

    final_abstract = "" if invalid_placeholder_abstract(abstract) else abstract
    final_conclusion = conclusion
    final_strengths = list(strengths or [])
    final_improvements = list(improvements or [])
    final_method = method
    final_scenario = scenario
    final_benchmark = benchmark
    final_contribution = contribution
    final_limitation = limitation
    role_normalization = apply_paper_role_exclusivity(
        {
            "abstract": final_abstract,
            "conclusion": final_conclusion,
            "strengths": final_strengths,
            "improvements": final_improvements,
            "contribution": final_contribution,
            "limitation": final_limitation,
        }
    )
    final_strengths = list(role_normalization["strengths"])
    final_improvements = list(role_normalization["improvements"])
    final_contribution = str(role_normalization["contribution"])
    final_limitation = str(role_normalization["limitation"])
    role_conflicts_resolved = list(role_normalization.get("role_conflicts_resolved") or [])
    context_text = "\n\n".join(part for part in [title, final_abstract, conclusion, full_text_excerpt, final_contribution, final_limitation] if part)
    final_full_text_enrichment = dict(full_text_enrichment or {})
    conversion_admission = (
        final_full_text_enrichment.get("evidence_admission")
        if isinstance(final_full_text_enrichment.get("evidence_admission"), dict)
        else {}
    )
    candidate_only_conversion = bool(
        conversion_admission
        and (
            conversion_admission.get("candidate_only")
            or str(conversion_admission.get("status") or "") in {
                "NEEDS_OCR", "DOCUMENT_INGESTION_FAILED", "TEXT_INTEGRITY_FAILED",
                "SECTION_STRUCTURE_PENDING", "SOURCE_LOCATORS_INCOMPLETE",
            }
        )
    )
    evidence_spans = final_full_text_enrichment.get("evidence_spans")
    if not isinstance(evidence_spans, list):
        evidence_spans = []
    if candidate_only_conversion:
        # A scan/OCR/supplement may be useful for discovery, but no automatic
        # causal claim, gap, or direct-evidence lane may originate from it.
        final_full_text_enrichment["unadmitted_evidence_span_count"] = len(evidence_spans)
        evidence_spans = []
    source_url = str(
        open_access_pdf
        or final_full_text_enrichment.get("source_url")
        or url
        or final_full_text_enrichment.get("source_path")
        or ""
    )
    initial_visual_evidence = _safe_visual_evidence_units(
        visual_evidence,
        paper_id=record_paper_id,
        sub_hypothesis_id=source_sub_hypothesis_id,
        source_pdf_url=source_url,
    )
    initial_visual_summary = _visual_evidence_summary(initial_visual_evidence)
    if initial_visual_evidence:
        final_full_text_enrichment["visual_evidence_summary"] = dict(
            initial_visual_summary
        )
        final_full_text_enrichment.setdefault(
            "multimodal_visual_evidence_gate_policy",
            "candidate_only_until_human_review",
        )
    methodology = extract_methodology_evidence(
        context_text,
        evidence_spans=evidence_spans,
        source_url=source_url,
    )
    final_method = prefer_structured_field(final_method, str(methodology.get("method") or ""), "method")
    final_scenario = prefer_structured_field(final_scenario, str(methodology.get("scenario") or ""), "scenario")
    final_benchmark = prefer_structured_field(final_benchmark, str(methodology.get("benchmark") or ""), "benchmark")
    final_method = repair_unknown_field(final_method, context_text, "method")
    final_scenario = repair_unknown_field(final_scenario, context_text, "scenario")
    final_benchmark = repair_unknown_field(final_benchmark, context_text, "benchmark")
    if research_question_evidence_v3:
        # Assertion extraction below is the only V3 scientific-evidence
        # projection.  These fields are not partially migrated because an
        # inferred old edge is not an EvidenceAssertion.
        extracted_gap_signals: list[dict[str, Any]] = []
        final_gap_signals: list[dict[str, Any]] = []
        final_causal_chains: list[dict[str, Any]] = []
        speculative_causal_signals: list[dict[str, Any]] = []
        association_signals: list[dict[str, Any]] = []
        final_full_text_enrichment["legacy_causal_projection"] = {
            "status": "STALE_SCHEMA",
            "accepted_by_research_question_evidence_v3": False,
            "reason": "V3 imports persist source-bound assertions instead of causal-chain or lexical-gap artifacts.",
        }
    final_full_text_enrichment["structured_methodology"] = methodology
    final_full_text_enrichment["association_signals"] = association_signals
    final_full_text_enrichment["speculative_causal_signals"] = speculative_causal_signals
    if final_gap_signals and is_unknown_value(final_limitation):
        final_limitation = str(final_gap_signals[0].get("text", final_limitation))
    elif final_gap_signals and final_limitation == "No explicit limitation extracted.":
        final_limitation = str(final_gap_signals[0].get("text", final_limitation))
    role_normalization = apply_paper_role_exclusivity(
        {
            "abstract": final_abstract,
            "conclusion": final_conclusion,
            "strengths": final_strengths,
            "improvements": final_improvements,
            "contribution": final_contribution,
            "limitation": final_limitation,
            "role_conflicts_resolved": role_conflicts_resolved,
        }
    )
    final_strengths = list(role_normalization["strengths"])
    final_improvements = list(role_normalization["improvements"])
    final_contribution = str(role_normalization["contribution"])
    final_limitation = str(role_normalization["limitation"])
    role_conflicts_resolved = list(role_normalization.get("role_conflicts_resolved") or [])
    final_extraction_quality = dict(extraction_quality or {}) or extraction_quality_report(
        {
            "title": title,
            "abstract": final_abstract,
            "conclusion": final_conclusion,
            "full_text_excerpt": full_text_excerpt,
            "method": final_method,
            "scenario": final_scenario,
            "benchmark": final_benchmark,
            "contribution": final_contribution,
            "limitation": final_limitation,
        }
    )
    final_extraction_quality["rule_extraction"] = {
        "methodology_evidence_count": len(methodology.get("evidence") or []),
        "causal_chain_count": len(final_causal_chains),
        "speculative_causal_signal_count": len(speculative_causal_signals),
        "association_signal_count": len(association_signals),
        "gap_signal_count": len(final_gap_signals),
        "evidence_span_count": len(evidence_spans),
    }
    final_extraction_quality["role_exclusivity"] = {
        "conflicts_resolved": len(role_conflicts_resolved),
        "resolutions": role_conflicts_resolved,
    }
    score, reasons = score_evidence_credibility(
        title=title,
        citation=citation,
        provider=provider,
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_scholar_id,
        url=url,
        abstract=final_abstract,
        conclusion=final_conclusion,
        venue=venue,
        year=year,
    )
    record = PaperGraphRecord(
        paper_id=record_paper_id,
        unique_key=unique_key,
        title=title,
        citation=citation,
        authors=list(authors or []),
        year=str(year),
        venue=venue,
        provider=provider,
        source_type=source_type,
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_scholar_id,
        openalex_id=openalex_id,
        url=url,
        abstract=final_abstract,
        full_text_excerpt=full_text_excerpt,
        conclusion=final_conclusion,
        strengths=final_strengths,
        improvements=final_improvements,
        method=final_method,
        scenario=final_scenario,
        benchmark=final_benchmark,
        contribution=final_contribution,
        limitation=final_limitation,
        credibility_score=score,
        credibility_reasons=reasons,
        extraction_quality=final_extraction_quality,
        enrichment_sources=list(enrichment_sources or []),
        open_access_pdf=open_access_pdf,
        full_text_enrichment=final_full_text_enrichment,
        gap_signals=final_gap_signals,
        causal_chains=final_causal_chains,
    )
    record_payload = asdict(record)
    if isinstance(document_descriptor, dict) and document_descriptor:
        record_payload["document_descriptor"] = deepcopy(document_descriptor)
    if research_question_evidence_v3:
        record_payload.pop("gap_signals", None)
        record_payload.pop("causal_chains", None)
        record_payload["evidence_pipeline_schema"] = "research_question_evidence_v3"
        record_payload["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
    record_payload["canonical_paper_key"] = paper_identity["canonical_key"]
    record_payload["paper_identity"] = {
        "kind": paper_identity["identity_kind"],
        "canonical_key": paper_identity["canonical_key"],
    }
    record_payload["paper_identity_aliases"] = paper_identity["aliases"]
    genre_assessment = (
        dict(paper_genre_assessment)
        if isinstance(paper_genre_assessment, dict) and paper_genre_assessment
        else {
            "schema_version": "paper_genre_assessment_v2",
            "genre": "unknown",
            "evidence_genre": "unknown",
            "research_design": "unknown",
            "publication_form": "unknown",
            "is_review": False,
            "status": "CLASSIFICATION_PENDING",
            "reason_codes": ["PAPER_CLASSIFICATION_REQUIRED"],
            "source_anchors": [],
        }
    )
    if candidate_only_conversion:
        genre_assessment = restrict_candidate_only_document_genre(genre_assessment, conversion_admission)
    record_payload["paper_genre"] = genre_assessment
    if research_question_evidence_v3:
        dual_axis_assessment: dict[str, Any] = {}
    else:
        causal_responsibility = classify_causal_role(
            record_payload,
            paper_genre=genre_assessment,
        )
        dual_axis_assessment = {
            "research_design": str(
                (alignment_assessment or {}).get("research_design")
                or genre_assessment.get("research_design")
                or "unclassified"
            ),
            "causal_role": str(
                (alignment_assessment or {}).get("causal_role")
                or causal_responsibility.get("causal_role")
                or "unclassified"
            ),
            "evidence_strength": str(
                (alignment_assessment or {}).get("evidence_strength")
                or causal_responsibility.get("evidence_strength")
                or "unclassified"
            ),
            "causal_validation_status": str(
                (alignment_assessment or {}).get("causal_validation_status")
                or causal_responsibility.get("causal_validation_status")
                or "unresolved"
            ),
            "supported_causal_roles": list(
                (alignment_assessment or {}).get("supported_causal_roles")
                or causal_responsibility.get("supported_causal_roles")
                or []
            ),
        }
        record_payload.update(dual_axis_assessment)
    # Preserve source-specific identifiers and impact measurements.  In
    # particular, OpenAlex cited-by counts must never be mistaken for or
    # overwrite a later Semantic Scholar enrichment value.
    if isinstance(provider_provenance, dict) and provider_provenance:
        record_payload["provider_provenance"] = dict(provider_provenance)
    if isinstance(paper_domain_assessment, dict) and paper_domain_assessment:
        record_payload["paper_domain_assessment"] = dict(paper_domain_assessment)
    if isinstance(paper_classification, dict) and paper_classification:
        record_payload["paper_classification"] = dict(paper_classification)
    if isinstance(external_ids, dict) and external_ids:
        record_payload["external_ids"] = dict(external_ids)
    if isinstance(citation_metrics, dict) and citation_metrics:
        record_payload["citation_metrics"] = dict(citation_metrics)
    record_payload["active"] = True
    if initial_visual_evidence:
        record_payload["visual_evidence"] = list(initial_visual_evidence)
        record_payload["visual_evidence_summary"] = dict(initial_visual_summary)
        record_payload["visual_evidence_counts_toward_gate"] = False
        record_payload["visual_evidence_gate_policy"] = (
            "candidate_only_until_human_review"
        )
    if retrieval_query:
        record_payload["retrieval_query"] = retrieval_query
    if isinstance(domain_relevance, dict):
        record_payload["domain_relevance"] = dict(domain_relevance)
    if isinstance(domain_review, dict):
        record_payload["domain_review"] = dict(domain_review)
    if isinstance(domain_gate, dict):
        record_payload["domain_gate"] = dict(domain_gate)
    if isinstance(domain_override, dict) and domain_override:
        record_payload["domain_override"] = dict(domain_override)
    if research_role:
        record_payload["research_role"] = str(research_role).upper()
    if isinstance(research_role_assessment, dict):
        record_payload["research_role_assessment"] = dict(research_role_assessment)
    if research_question_card_version:
        record_payload["research_question_card_version"] = research_question_card_version
    if isinstance(alignment_assessment, dict) and alignment_assessment:
        record_payload["alignment_assessment"] = dict(alignment_assessment)
    if evidence_kind:
        record_payload["evidence_kind"] = str(evidence_kind)
    if isinstance(alignment_override, dict) and alignment_override:
        record_payload["alignment_override"] = dict(alignment_override)
    if isinstance(foundational_bridge_assessment, dict) and foundational_bridge_assessment:
        record_payload["foundational_bridge_assessment"] = dict(foundational_bridge_assessment)
    if isinstance(fulltext_structuring, dict) and fulltext_structuring:
        record_payload["fulltext_structuring"] = dict(fulltext_structuring)
    domain_review_verdict = str((domain_review or {}).get("verdict") or "")
    domain_gate_verdict = str((domain_gate or {}).get("verdict") or "")
    record_payload["requires_human_review"] = (
        domain_review_verdict == "review"
        or domain_gate_verdict in {"review", "override"}
        or bool((domain_gate or {}).get("requires_human_review"))
        or candidate_only_conversion
    )
    if normalized_import_context:
        record_payload["import_context"] = normalized_import_context
    import_scope = (
        normalized_import_context.get("retrieval_scope")
        if isinstance(normalized_import_context.get("retrieval_scope"), dict)
        else {}
    )
    v3_foundational_context = bool(
        str(import_scope.get("kind") or "") == "subhypothesis_foundational_context"
        or str(evidence_kind or "").strip().lower() == "foundational_context"
    )
    full_text_assessment = assess_full_text_acquisition(record_payload)
    fulltext_admission = fulltext_structuring_admission_assessment(record_payload)
    alignment_for_admission = (
        record_payload.get("alignment_assessment")
        if isinstance(record_payload.get("alignment_assessment"), dict)
        else alignment_assessment
        if isinstance(alignment_assessment, dict)
        else {}
    )
    post_admission_context = (
        (normalized_import_context or {}).get("post_fulltext_admission")
        if isinstance((normalized_import_context or {}).get("post_fulltext_admission"), dict)
        else {}
    )
    alignment_corpus_admission = (
        alignment_for_admission.get("corpus_admission")
        if isinstance(alignment_for_admission.get("corpus_admission"), dict)
        else {}
    )
    post_corpus_admission = (
        post_admission_context.get("corpus_admission")
        if isinstance(post_admission_context.get("corpus_admission"), dict)
        else {}
    )

    def _admission_field(key: str, default: Any = None) -> Any:
        for source in (
            alignment_for_admission,
            post_admission_context,
            alignment_corpus_admission,
            post_corpus_admission,
        ):
            if isinstance(source, Mapping) and key in source:
                return source.get(key)
        return default

    corpus_admitted = bool(
        alignment_for_admission.get("corpus_admitted")
        or post_admission_context.get("corpus_admitted")
        or (
            alignment_override.get("corpus_admitted")
            if isinstance(alignment_override, dict)
            else False
        )
    )
    corpus_admission_reason = str(
        alignment_for_admission.get("corpus_admission_reason")
        or post_admission_context.get("corpus_admission_reason")
        or (
            alignment_override.get("corpus_admission_reason")
            if isinstance(alignment_override, dict)
            else ""
        )
        or ""
    )
    evidence_role = str(
        alignment_for_admission.get("evidence_role")
        or post_admission_context.get("evidence_role")
        or (
            alignment_override.get("evidence_role")
            if isinstance(alignment_override, dict)
            else ""
        )
        or (
            "foundational_bridge"
            if isinstance(foundational_bridge_assessment, dict)
            and foundational_bridge_assessment
            else ""
        )
    )
    evidence_polarity = str(
        alignment_for_admission.get("evidence_polarity")
        or post_admission_context.get("evidence_polarity")
        or ""
    )
    sh_locality_scope = str(
        alignment_for_admission.get("sh_locality_scope")
        or post_admission_context.get("sh_locality_scope")
        or ""
    )
    policy_economic_context = bool(_admission_field("policy_economic_context", False))
    policy_economic_context_hits = [
        str(item)
        for item in (_admission_field("policy_economic_context_hits", []) or [])
        if str(item).strip()
    ][:16]
    policy_economic_context_demoted = bool(
        _admission_field("policy_economic_context_demoted", False)
    )
    policy_economic_demoted_scope = str(
        _admission_field("policy_economic_demoted_scope", "") or ""
    )
    sh_declares_policy_economic_endpoint = bool(
        _admission_field("sh_declares_policy_economic_endpoint", False)
    )
    sh_policy_economic_axis_hits = [
        str(item)
        for item in (_admission_field("sh_policy_economic_axis_hits", []) or [])
        if str(item).strip()
    ][:16]
    project_background_reason = str(
        _admission_field("project_background_reason", "") or ""
    )
    project_background_only = bool(
        alignment_for_admission.get("project_background_only")
        or alignment_for_admission.get("excluded_from_sh_gap_synthesis")
        or post_admission_context.get("project_background_only")
        or post_admission_context.get("excluded_from_sh_gap_synthesis")
        or sh_locality_scope == "project_background_only"
        or policy_economic_context_demoted
        or policy_economic_demoted_scope == "project_background_only"
    )
    counts_toward_component_bridge_gap = bool(
        alignment_for_admission.get("counts_toward_component_bridge_gap")
        or post_admission_context.get("counts_toward_component_bridge_gap")
    )
    gate_counting_evidence = bool(
        str(import_scope.get("kind") or "") == "subhypothesis"
        and full_text_assessment.get("full_text_available") is True
        and fulltext_admission.get("eligible_for_evidence_admission") is True
        and not project_background_only
        and (
            alignment_for_admission.get("import_eligible") is True
            or alignment_for_admission.get("core_eligible") is True
            or (
                isinstance(foundational_bridge_assessment, dict)
                and foundational_bridge_assessment.get("bridge_eligible") is True
                and foundational_bridge_assessment.get("revoked_after_full_text") is not True
            )
        )
    )
    if v3_foundational_context:
        # The V3 context lane is intentionally neither the historic causal
        # bridge nor an L1 admission shortcut. It is retained for explicit
        # source-bound rationale only after the normal document extraction.
        gate_counting_evidence = False
        corpus_admitted = False
        corpus_admission_reason = "v3_foundational_context_rationale_only"
        evidence_role = "foundational_context"
        sh_locality_scope = "sh_local_foundational_context"
        project_background_only = False
    corpus_target_counting_evidence = bool(
        (
            str(import_scope.get("kind") or "") == "subhypothesis"
            or bool(source_sub_hypothesis_id)
        )
        and full_text_assessment.get("full_text_available") is True
        and not alignment_for_admission.get("off_topic")
        and not alignment_for_admission.get("true_off_topic")
        and not alignment_for_admission.get("exclusion_hits")
        and not project_background_only
        and (
            corpus_admitted
            or gate_counting_evidence
            or alignment_for_admission.get("import_eligible") is True
            or alignment_for_admission.get("core_eligible") is True
            or counts_toward_component_bridge_gap
        )
    )
    if v3_foundational_context:
        corpus_target_counting_evidence = False
    corpus_evidence_tier = _corpus_evidence_tier_for_import(
        record_payload,
        alignment_for_admission,
        layer=str(
            normalized_import_context.get("stratified_layer") or "L4_regular"
        ),
    )
    if corpus_evidence_tier == "CORE_CONTRACT_SOURCE" and not gate_counting_evidence:
        corpus_evidence_tier = (
            "COMPONENT_BRIDGE"
            if "component"
            in str(
                evidence_kind
                or alignment_for_admission.get("evidence_kind")
                or ""
            ).lower()
            else "RELATED_CONTEXT"
        )
    full_text_excerpt_chars = int(full_text_assessment["full_text_excerpt_chars"])
    full_text_available = bool(full_text_assessment["full_text_available"])
    record_payload["full_text_acquisition"] = {
        "status": "AVAILABLE" if full_text_available else "ABSTRACT_OR_METADATA_ONLY",
        "available": full_text_available,
        "excerpt_chars": full_text_excerpt_chars,
        "target_policy": "subhypothesis_full_text_required_for_direct_evidence_v1",
        "structuring_status": fulltext_admission["status"],
        "eligible_for_evidence_admission": fulltext_admission[
            "eligible_for_evidence_admission"
        ],
    }
    record_payload["corpus_admitted"] = corpus_admitted
    record_payload["corpus_admission_reason"] = corpus_admission_reason
    record_payload["evidence_role"] = evidence_role
    record_payload["evidence_polarity"] = evidence_polarity or record_payload.get("evidence_polarity", "")
    record_payload["sh_locality_scope"] = sh_locality_scope
    record_payload["project_background_only"] = project_background_only
    record_payload["excluded_from_sh_gap_synthesis"] = project_background_only
    record_payload["counts_toward_component_bridge_gap"] = counts_toward_component_bridge_gap
    record_payload["project_background_reason"] = project_background_reason
    record_payload["policy_economic_context"] = policy_economic_context
    record_payload["policy_economic_context_hits"] = policy_economic_context_hits
    record_payload["policy_economic_context_demoted"] = policy_economic_context_demoted
    record_payload["policy_economic_demoted_scope"] = policy_economic_demoted_scope
    record_payload[
        "sh_declares_policy_economic_endpoint"
    ] = sh_declares_policy_economic_endpoint
    record_payload["sh_policy_economic_axis_hits"] = sh_policy_economic_axis_hits
    record_payload["fulltext_structurally_usable"] = bool(full_text_available)
    record_payload["fulltext_evidence_admissible"] = bool(full_text_available)
    record_payload["gate_counting_evidence"] = gate_counting_evidence
    record_payload[
        "corpus_target_counting_evidence"
    ] = corpus_target_counting_evidence
    record_payload["corpus_evidence_tier"] = corpus_evidence_tier
    if v3_foundational_context:
        record_payload["foundation_context_status"] = "PENDING_V3_CONTEXT_ADMISSION"
        record_payload["direct_evidence_eligible"] = False
        record_payload["core_eligible"] = False
        record_payload["stratified_layer"] = ""
    relatedness_axes = _alignment_relatedness_axes_for_log(alignment_for_admission)
    missing_contract_requirements = _alignment_missing_contract_requirements_for_log(
        alignment_for_admission
    )
    demotion_reason = _noncore_demotion_reason_for_log(
        alignment_for_admission,
        missing_contract_requirements,
    )
    auxiliary_allowed = bool(
        alignment_for_admission.get("auxiliary_eligible") is True
        or (
            isinstance(foundational_bridge_assessment, dict)
            and foundational_bridge_assessment
        )
        or evidence_role
        in {
            "method_or_platform_context",
            "foundational_bridge",
            "component_bridge_evidence",
            "background_review",
            "related_reserve",
            "boundary_or_generalization",
            "adverse_or_reversal",
        }
    )
    record_payload["auxiliary_eligible"] = bool(
        corpus_admitted
        and not gate_counting_evidence
        and not project_background_only
        and auxiliary_allowed
        and str(import_scope.get("kind") or "") == "subhypothesis"
    )
    record_payload["relatedness_axes"] = relatedness_axes
    record_payload["missing_contract_requirements"] = missing_contract_requirements
    record_payload["demotion_reason"] = (
        demotion_reason if record_payload["auxiliary_eligible"] else ""
    )
    record_payload["next_use"] = (
        "project_context_only"
        if project_background_only
        else
        "corpus_classification_and_gap_generation"
        if record_payload["auxiliary_eligible"]
        else "core_gate_or_background_only"
        if gate_counting_evidence
        else "corpus_reserve"
        if corpus_admitted
        else ""
    )
    if str(import_scope.get("kind") or "") == "subhypothesis" and not full_text_available:
        record_payload["direct_evidence_eligible"] = False
        record_payload["core_eligible"] = False
        if isinstance(record_payload.get("alignment_assessment"), dict):
            record_payload["alignment_assessment"] = {
                **record_payload["alignment_assessment"],
                "core_eligible": False,
                "full_text_required_for_core_evidence": True,
            }
    elif (
        str(import_scope.get("kind") or "") == "subhypothesis"
        and not fulltext_admission["eligible_for_evidence_admission"]
    ):
        # Preserve the deterministic post-full-text alignment audit for a
        # later structuring retry, but prevent this cached document from
        # advancing any L0/L1/L2/L4 or direct-core evidence gate meanwhile.
        record_payload["direct_evidence_eligible"] = False
        record_payload["core_eligible"] = False
        record_payload["fulltext_pending_structuring"] = True
    if str(import_scope.get("kind") or "") == "ad_hoc_discovery":
        record_payload["ad_hoc_discovery"] = True
        record_payload["direct_evidence_eligible"] = False
        record_payload["research_role"] = "BACKGROUND"
        record_payload["requires_human_review"] = True
    claim_effect = _papergraph_claim_effect_annotations(
        import_context=normalized_import_context,
        alignment_assessment=(
            record_payload.get("alignment_assessment")
            if isinstance(record_payload.get("alignment_assessment"), dict)
            else alignment_assessment
        ),
        record_payload=record_payload,
    )
    record_payload.update(claim_effect)
    if isinstance(record_payload.get("alignment_assessment"), dict):
        record_payload["alignment_assessment"] = {
            **record_payload["alignment_assessment"],
            **claim_effect,
        }
    if normalized_import_context:
        record_payload["import_context"] = {
            **normalized_import_context,
            "evidence_path_role": str(
                normalized_import_context.get("evidence_path_role")
                or claim_effect.get("evidence_path_role")
                or ""
            ),
            "evidence_path_polarity": str(
                normalized_import_context.get("evidence_path_polarity")
                or claim_effect.get("evidence_path_polarity")
                or claim_effect.get("evidence_polarity")
                or ""
            ),
        }
        normalized_import_context = dict(record_payload["import_context"])
    if v3_binding_expected and not source_sub_hypothesis_id:
        record_payload["v3_unbound_import_diagnostics"] = [
            {
                "reason_code": "EXPLICIT_V3_SUBHYPOTHESIS_PROVENANCE_MISSING",
                "research_question_contract_id": str(
                    normalized_import_context.get("research_question_contract_id")
                    or ""
                ),
                "research_question_contract_revision": str(
                    normalized_import_context.get("research_question_contract_revision")
                    or ""
                ),
                "research_question_contract_hash": str(
                    normalized_import_context.get("research_question_contract_hash")
                    or ""
                ),
                "source_search_id": str(
                    normalized_import_context.get("search_id") or ""
                ),
                "source_result_index": normalized_import_context.get("result_index"),
                "recorded_at": time.time(),
            }
        ]
    if retrieval_branch:
        record_payload["retrieval_branch"] = retrieval_branch
    if isinstance(subhypothesis_bindings, list) and subhypothesis_bindings:
        record_payload["subhypothesis_bindings"] = [
            deepcopy(item)
            for item in subhypothesis_bindings
            if isinstance(item, dict)
        ]
    elif source_sub_hypothesis_id:
        record_payload["subhypothesis_bindings"] = [
            {
                "sub_hypothesis_id": source_sub_hypothesis_id,
                "research_question_contract_id": str(
                    normalized_import_context.get(
                        "research_question_contract_id"
                    )
                    or ""
                ),
                "research_question_contract_revision": str(
                    normalized_import_context.get(
                        "research_question_contract_revision"
                    )
                    or ""
                ),
                "research_question_contract_hash": str(
                    normalized_import_context.get(
                        "research_question_contract_hash"
                    )
                    or normalized_import_context.get(
                        "research_question_contract_revision"
                    )
                    or ""
                ),
                "groupchat_id": str(normalized_import_context.get("groupchat_id") or ""),
                "run_id": str(normalized_import_context.get("run_id") or ""),
                "retrieval_wave_id": str(normalized_import_context.get("retrieval_wave_id") or ""),
                "query_branch_id": str(normalized_import_context.get("query_branch_id") or ""),
                "query_branch_role": str(normalized_import_context.get("query_branch_role") or ""),
                "research_question_task_id": str(normalized_import_context.get("research_question_task_id") or ""),
                "target_slot_ids": [
                    str(value)
                    for value in normalized_import_context.get("target_slot_ids") or (
                        [normalized_import_context.get("evidence_slot") or ""]
                        if normalized_import_context.get("evidence_slot")
                        else []
                    )
                    if str(value)
                ],
                "alignment_scope_id": str(normalized_import_context.get("alignment_scope_id") or ""),
                "alignment_scope_revision": str(normalized_import_context.get("alignment_scope_revision") or ""),
                "object_scope": dict(normalized_import_context.get("object_scope") or {}),
                "evidence_slot": str(normalized_import_context.get("evidence_slot") or ""),
                "query_mode": str(normalized_import_context.get("query_mode") or ""),
                "candidate_rank": normalized_import_context.get("candidate_rank"),
                "provider": str(normalized_import_context.get("provider") or ""),
                "stratified_layer": str(normalized_import_context.get("stratified_layer") or "L4_regular"),
                "evidence_kind": str(evidence_kind or normalized_import_context.get("evidence_kind") or ""),
                "evidence_path_role": str(normalized_import_context.get("evidence_path_role") or ""),
                "evidence_path_polarity": str(normalized_import_context.get("evidence_path_polarity") or ""),
                "evidence_polarity": str(claim_effect.get("evidence_polarity") or ""),
                "supports_primary_claim": bool(claim_effect.get("supports_primary_claim")),
                "weakens_primary_claim": bool(claim_effect.get("weakens_primary_claim")),
                "boundary_condition_supported": bool(claim_effect.get("boundary_condition_supported")),
                "target_lane": str(normalized_import_context.get("target_lane") or ""),
                "retrieval_layer_role": str(normalized_import_context.get("retrieval_layer_role") or ""),
                "core_evidence_capable": normalized_import_context.get("core_evidence_capable"),
                "can_independently_falsify_sh": normalized_import_context.get("can_independently_falsify_sh"),
                "failure_scope": str(normalized_import_context.get("failure_scope") or ""),
                "corpus_admitted": bool(record_payload.get("corpus_admitted")),
                "auxiliary_eligible": bool(record_payload.get("auxiliary_eligible")),
                "gate_counting_evidence": bool(record_payload.get("gate_counting_evidence")),
                "corpus_target_counting_evidence": bool(
                    record_payload.get("corpus_target_counting_evidence")
                ),
                "corpus_evidence_tier": str(
                    record_payload.get("corpus_evidence_tier") or ""
                ),
                "sh_locality_scope": str(
                    record_payload.get("sh_locality_scope") or ""
                ),
                "project_background_only": bool(
                    record_payload.get("project_background_only")
                ),
                "excluded_from_sh_gap_synthesis": bool(
                    record_payload.get("excluded_from_sh_gap_synthesis")
                ),
                "project_background_reason": str(
                    record_payload.get("project_background_reason") or ""
                ),
                "policy_economic_context": bool(
                    record_payload.get("policy_economic_context")
                ),
                "policy_economic_context_hits": list(
                    record_payload.get("policy_economic_context_hits") or []
                ),
                "policy_economic_context_demoted": bool(
                    record_payload.get("policy_economic_context_demoted")
                ),
                "policy_economic_demoted_scope": str(
                    record_payload.get("policy_economic_demoted_scope") or ""
                ),
                "sh_declares_policy_economic_endpoint": bool(
                    record_payload.get("sh_declares_policy_economic_endpoint")
                ),
                "sh_policy_economic_axis_hits": list(
                    record_payload.get("sh_policy_economic_axis_hits") or []
                ),
                "counts_toward_component_bridge_gap": bool(
                    record_payload.get("counts_toward_component_bridge_gap")
                ),
                "demotion_reason": str(record_payload.get("demotion_reason") or ""),
                "relatedness_axes": list(record_payload.get("relatedness_axes") or []),
                "missing_contract_requirements": list(
                    record_payload.get("missing_contract_requirements") or []
                ),
                "next_use": str(record_payload.get("next_use") or ""),
                "alignment_assessment": dict(alignment_assessment or {}),
                "foundational_bridge_assessment": dict(foundational_bridge_assessment or {}),
                "fulltext_structuring": dict(
                    fulltext_structuring
                    or (
                        normalized_import_context.get("post_fulltext_admission")
                        or {}
                    ).get("fulltext_structuring")
                    or {}
                ),
                "source_search_id": str(normalized_import_context.get("search_id") or ""),
                "source_result_index": normalized_import_context.get("result_index"),
                "bound_at": time.time(),
            }
        ]
    evidence_payload = asdict(
        PaperEvidence(
            evidence_id=new_id("ev"),
            title=title,
            citation=citation,
            method=final_method,
            scenario=final_scenario,
            benchmark=final_benchmark,
            contribution=final_contribution,
            limitation=final_limitation,
            url=url,
        )
    )
    evidence_payload["paper_id"] = record.paper_id
    evidence_payload["active"] = True
    if research_question_evidence_v3:
        evidence_payload["evidence_pipeline_schema"] = "research_question_evidence_v3"
        evidence_payload["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
    else:
        evidence_payload["causal_chains"] = final_causal_chains
    evidence_payload.update(dual_axis_assessment)
    if isinstance(alignment_assessment, dict) and alignment_assessment:
        evidence_payload["alignment_assessment"] = dict(alignment_assessment)
    if evidence_kind:
        evidence_payload["evidence_kind"] = str(evidence_kind)
    if isinstance(foundational_bridge_assessment, dict) and foundational_bridge_assessment:
        evidence_payload["foundational_bridge_assessment"] = dict(foundational_bridge_assessment)
    evidence_payload["paper_genre"] = genre_assessment
    if isinstance(paper_domain_assessment, dict) and paper_domain_assessment:
        evidence_payload["paper_domain_assessment"] = dict(paper_domain_assessment)
    if isinstance(paper_classification, dict) and paper_classification:
        evidence_payload["paper_classification"] = dict(paper_classification)
    evidence_payload["full_text_acquisition"] = dict(record_payload["full_text_acquisition"])
    evidence_payload["fulltext_structuring"] = dict(
        record_payload.get("fulltext_structuring") or {}
    )
    if initial_visual_evidence:
        evidence_payload["visual_evidence_summary"] = dict(initial_visual_summary)
        evidence_payload["visual_evidence_counts_toward_gate"] = False
        evidence_payload["visual_evidence_gate_policy"] = (
            "candidate_only_until_human_review"
        )
    evidence_payload["corpus_admitted"] = corpus_admitted
    evidence_payload["corpus_admission_reason"] = corpus_admission_reason
    evidence_payload["evidence_role"] = evidence_role
    evidence_payload["evidence_polarity"] = evidence_polarity or evidence_payload.get("evidence_polarity", "")
    evidence_payload["sh_locality_scope"] = sh_locality_scope
    evidence_payload["project_background_only"] = project_background_only
    evidence_payload["excluded_from_sh_gap_synthesis"] = project_background_only
    evidence_payload["counts_toward_component_bridge_gap"] = counts_toward_component_bridge_gap
    evidence_payload["project_background_reason"] = project_background_reason
    evidence_payload["policy_economic_context"] = policy_economic_context
    evidence_payload["policy_economic_context_hits"] = policy_economic_context_hits
    evidence_payload["policy_economic_context_demoted"] = policy_economic_context_demoted
    evidence_payload["policy_economic_demoted_scope"] = policy_economic_demoted_scope
    evidence_payload[
        "sh_declares_policy_economic_endpoint"
    ] = sh_declares_policy_economic_endpoint
    evidence_payload["sh_policy_economic_axis_hits"] = sh_policy_economic_axis_hits
    evidence_payload["fulltext_structurally_usable"] = bool(full_text_available)
    evidence_payload["fulltext_evidence_admissible"] = bool(full_text_available)
    evidence_payload["gate_counting_evidence"] = gate_counting_evidence
    evidence_payload[
        "corpus_target_counting_evidence"
    ] = corpus_target_counting_evidence
    evidence_payload["corpus_evidence_tier"] = corpus_evidence_tier
    if v3_foundational_context:
        evidence_payload["foundation_context_status"] = "PENDING_V3_CONTEXT_ADMISSION"
        evidence_payload["direct_evidence_eligible"] = False
        evidence_payload["core_eligible"] = False
    evidence_payload["auxiliary_eligible"] = bool(record_payload.get("auxiliary_eligible"))
    evidence_payload["relatedness_axes"] = list(record_payload.get("relatedness_axes") or [])
    evidence_payload["missing_contract_requirements"] = list(
        record_payload.get("missing_contract_requirements") or []
    )
    evidence_payload["demotion_reason"] = str(record_payload.get("demotion_reason") or "")
    evidence_payload["next_use"] = str(record_payload.get("next_use") or "")
    if str(import_scope.get("kind") or "") == "subhypothesis" and not full_text_available:
        evidence_payload["direct_evidence_eligible"] = False
        evidence_payload["core_eligible"] = False
        if isinstance(evidence_payload.get("alignment_assessment"), dict):
            evidence_payload["alignment_assessment"] = {
                **evidence_payload["alignment_assessment"],
                "core_eligible": False,
                "full_text_required_for_core_evidence": True,
            }
    elif (
        str(import_scope.get("kind") or "") == "subhypothesis"
        and not fulltext_admission["eligible_for_evidence_admission"]
    ):
        evidence_payload["direct_evidence_eligible"] = False
        evidence_payload["core_eligible"] = False
        evidence_payload["fulltext_pending_structuring"] = True
    if candidate_only_conversion:
        evidence_payload["candidate_only_document"] = True
    if str(import_scope.get("kind") or "") == "ad_hoc_discovery":
        evidence_payload["ad_hoc_discovery"] = True
        evidence_payload["direct_evidence_eligible"] = False
        evidence_payload["research_role"] = "BACKGROUND"
    evidence_payload.update(claim_effect)
    if isinstance(evidence_payload.get("alignment_assessment"), dict):
        evidence_payload["alignment_assessment"] = {
            **evidence_payload["alignment_assessment"],
            **claim_effect,
        }
    is_subhypothesis_import = bool(
        str(import_scope.get("kind") or "") == "subhypothesis"
        or source_sub_hypothesis_id
    )
    core_eligible_for_log = bool(
        evidence_payload.get("core_eligible")
        or record_payload.get("core_eligible")
        or (
            (alignment_assessment or {}).get("core_eligible")
            and gate_counting_evidence
        )
    )
    standard_core_eligible_for_log = bool(
        (alignment_assessment or {}).get("standard_core_eligible")
        or evidence_payload.get("standard_core_eligible")
        or record_payload.get("standard_core_eligible")
    )
    if not is_subhypothesis_import:
        admission_scope = "ad_hoc"
    elif project_background_only:
        admission_scope = "project_background_only"
    elif v3_foundational_context:
        admission_scope = "foundational_context"
    elif foundational_bridge_assessment:
        admission_scope = "foundation"
    elif core_eligible_for_log or standard_core_eligible_for_log:
        admission_scope = "core_or_core_compatible"
    elif sh_locality_scope == "component_bridge_evidence":
        admission_scope = "component_bridge_evidence"
    elif sh_locality_scope == "sh_local_auxiliary":
        admission_scope = "sh_local_auxiliary"
    elif corpus_admitted and not gate_counting_evidence:
        admission_scope = "sh_local_auxiliary"
    elif evidence_payload.get("direct_evidence_eligible") is False:
        admission_scope = "metadata_or_pending_fulltext"
    else:
        admission_scope = "auxiliary"
    counts_toward_gate = bool(gate_counting_evidence and not project_background_only)
    counts_toward_corpus_target = bool(
        corpus_target_counting_evidence and not project_background_only
    )
    record_payload["admission_scope"] = admission_scope
    record_payload["counts_toward_gate"] = counts_toward_gate
    record_payload["counts_toward_corpus_target"] = counts_toward_corpus_target
    evidence_payload["admission_scope"] = admission_scope
    evidence_payload["counts_toward_gate"] = counts_toward_gate
    evidence_payload["counts_toward_corpus_target"] = counts_toward_corpus_target
    # A direct ``gap_source_admission`` is no longer written here.  Admission
    # is computed from the question-specific source spans below and is keyed
    # by the v2 research-question contract.  Import-time corpus eligibility
    # remains useful metadata, but it cannot be reused as scientific-gap
    # authority for a different question.
    if project_background_only:
        record_payload["next_use"] = "project_context_only"
        evidence_payload["next_use"] = "project_context_only"
        record_payload["claim_strength_effect"] = "no_claim_strength_increase"
        evidence_payload["claim_strength_effect"] = "no_claim_strength_increase"
    for payload in (record_payload, evidence_payload):
        assessment_payload = payload.get("alignment_assessment")
        if isinstance(assessment_payload, dict):
            payload["alignment_assessment"] = {
                **assessment_payload,
                "admission_scope": admission_scope,
                "counts_toward_gate": counts_toward_gate,
                "counts_toward_corpus_target": counts_toward_corpus_target,
                "project_background_only": project_background_only,
                "excluded_from_sh_gap_synthesis": project_background_only,
                "project_background_reason": project_background_reason,
                "policy_economic_context": policy_economic_context,
                "policy_economic_context_hits": policy_economic_context_hits,
                "policy_economic_context_demoted": policy_economic_context_demoted,
                "policy_economic_demoted_scope": policy_economic_demoted_scope,
                "sh_declares_policy_economic_endpoint": sh_declares_policy_economic_endpoint,
                "sh_policy_economic_axis_hits": sh_policy_economic_axis_hits,
            }
    if isinstance(record_payload.get("import_context"), dict):
        record_payload["import_context"] = {
            **record_payload["import_context"],
            "admission_scope": admission_scope,
            "counts_toward_gate": counts_toward_gate,
            "counts_toward_corpus_target": counts_toward_corpus_target,
            "project_background_only": project_background_only,
            "excluded_from_sh_gap_synthesis": project_background_only,
            "project_background_reason": project_background_reason,
            "policy_economic_context": policy_economic_context,
            "policy_economic_context_hits": policy_economic_context_hits,
            "policy_economic_context_demoted": policy_economic_context_demoted,
            "policy_economic_demoted_scope": policy_economic_demoted_scope,
            "sh_declares_policy_economic_endpoint": sh_declares_policy_economic_endpoint,
            "sh_policy_economic_axis_hits": sh_policy_economic_axis_hits,
        }
    for binding in record_payload.get("subhypothesis_bindings") or []:
        if isinstance(binding, dict):
            binding["admission_scope"] = admission_scope
            binding["corpus_admitted"] = corpus_admitted
            binding["counts_toward_gate"] = counts_toward_gate
            binding["counts_toward_corpus_target"] = counts_toward_corpus_target
            binding["project_background_only"] = project_background_only
            binding["excluded_from_sh_gap_synthesis"] = project_background_only
            binding["project_background_reason"] = project_background_reason
            binding["policy_economic_context"] = policy_economic_context
            binding["policy_economic_context_hits"] = list(policy_economic_context_hits)
            binding["policy_economic_context_demoted"] = policy_economic_context_demoted
            binding["policy_economic_demoted_scope"] = policy_economic_demoted_scope
            binding[
                "sh_declares_policy_economic_endpoint"
            ] = sh_declares_policy_economic_endpoint
            binding["sh_policy_economic_axis_hits"] = list(
                sh_policy_economic_axis_hits
            )
            if project_background_only:
                binding["next_use"] = "project_context_only"

    # The import is question-bound rather than branch-name-bound.  A V3
    # document must carry the exact current contract id on each explicit
    # binding before assertion extraction; a stale/missing SH id is retained
    # as an unlinked source diagnostic instead of being attached by lexical
    # similarity or a legacy alignment contract.
    if research_question_evidence_v3:
        contracts_by_subhypothesis = {
            str(item.get("id") or item.get("sub_hypothesis_id") or ""): item.get("research_question_contract")
            for item in project.get("sub_hypotheses", [])
            if isinstance(item, dict)
            and isinstance(item.get("research_question_contract"), dict)
            and item["research_question_contract"].get("schema_version")
            == "research_question_contract_v3"
        }
        for binding in record_payload.get("subhypothesis_bindings") or []:
            if not isinstance(binding, dict):
                continue
            binding_contract_id = str(
                binding.get("research_question_contract_id") or ""
            )
            contract = contracts_by_subhypothesis.get(
                str(binding.get("sub_hypothesis_id") or "")
            )
            if isinstance(contract, dict) and not binding_contract_id:
                binding["research_question_contract_id"] = str(contract.get("contract_id") or "")
                binding["research_question_contract_revision"] = str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                )
                binding["research_question_contract_hash"] = str(
                    contract.get("declaration_hash") or contract.get("contract_revision") or ""
                )
                # The scalar record fields are the import event's local
                # compatibility surface.  The binding is authoritative for a
                # contract-specific V3 decision and must retain the same
                # corpus/gate outcome when a duplicate paper is later bound to
                # another SH.
                binding["corpus_admitted"] = bool(corpus_admitted)
                binding["counts_toward_gate"] = bool(counts_toward_gate)
                binding["fulltext_structuring"] = dict(
                    record_payload.get("fulltext_structuring") or {}
                )
        bound_contract = contracts_by_subhypothesis.get(source_sub_hypothesis_id)
        if isinstance(bound_contract, dict):
            record_payload["research_question_contract_id"] = str(bound_contract.get("contract_id") or "")
            record_payload["research_question_contract_revision"] = str(
                bound_contract.get("contract_revision")
                or bound_contract.get("declaration_hash")
                or ""
            )
            record_payload["research_question_contract_hash"] = str(
                bound_contract.get("declaration_hash")
                or bound_contract.get("contract_revision")
                or ""
            )
            record_payload.setdefault("import_context", {}).update({
                "research_question_contract_id": str(
                    bound_contract.get("contract_id") or ""
                ),
                "research_question_contract_revision": str(
                    bound_contract.get("contract_revision")
                    or bound_contract.get("declaration_hash")
                    or ""
                ),
                "research_question_contract_hash": str(
                    bound_contract.get("declaration_hash")
                    or bound_contract.get("contract_revision")
                    or ""
                ),
            })
        elif source_sub_hypothesis_id:
            record_payload["research_question_binding_status"] = "UNRESOLVED_V3_SUBHYPOTHESIS_ID"

    # Persist source spans and explicit assertions as part of the import
    # transaction.  The same helper is called for duplicate enrichments, so a
    # later full-text upgrade cannot leave a stale assertion projection.
    evidence_projection_result = persist_question_bound_evidence_assertions(
        project,
        record_payload,
        evidence_record=evidence_payload,
        use_llm=use_llm,
        prepared_extraction=prepared_evidence_artifact,
    )
    projection_status = str(evidence_projection_result.get("status") or "")
    if projection_status == "COMMIT_REJECTED":
        apply_evidence_status_dominance(
            record_payload,
            evidence_payload,
            status=projection_status,
            reason_codes=list(evidence_projection_result.get("reason_codes") or []),
        )
    if projection_status == "COMMIT_REJECTED":
        log_event(
            "WARN",
            "candidate_commit_rejected",
            project_id=project_id,
            paper_id=str(record_payload.get("paper_id") or ""),
            protocol_status=str(evidence_projection_result.get("protocol_status") or ""),
            reason_codes=list(evidence_projection_result.get("reason_codes") or []),
        )
        return json.dumps(
            {
                "status": "commit_rejected",
                "paper_id": str(record_payload.get("paper_id") or ""),
                "protocol_status": str(
                    evidence_projection_result.get("protocol_status") or ""
                ),
                "reason_codes": list(
                    evidence_projection_result.get("reason_codes") or []
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    if str(record_payload.get("evidence_preparation_status") or "") in {
        "ALIGNMENT_PENDING",
        "PROPOSITION_PARTIAL",
        "COMPOSITION_PENDING",
        "LLM_DISABLED",
        "LLM_EXTRACTION_PENDING",
    }:
        gate_counting_evidence = False
        counts_toward_gate = False
        counts_toward_corpus_target = False
        core_eligible_for_log = False
        standard_core_eligible_for_log = False
    foundation_context_admission = assess_foundational_context_v3_admission(
        record_payload
    )
    if foundation_context_admission["status"] != "NOT_V3_FOUNDATIONAL_CONTEXT":
        record_payload["foundation_context_admission"] = foundation_context_admission
        evidence_payload["foundation_context_admission"] = dict(
            foundation_context_admission
        )
        record_payload["foundation_context_status"] = foundation_context_admission[
            "status"
        ]
        evidence_payload["foundation_context_status"] = foundation_context_admission[
            "status"
        ]
        if foundation_context_admission.get("admitted"):
            record_payload["stratified_layer"] = "L1_milestone"
            evidence_payload["stratified_layer"] = "L1_milestone"
            record_payload.setdefault("import_context", {})[
                "stratified_layer"
            ] = "L1_milestone"
            for binding in record_payload.get("subhypothesis_bindings") or []:
                if isinstance(binding, dict):
                    binding["stratified_layer"] = "L1_milestone"
        log_event(
            "SCIENCE",
            "v3_foundational_context_admission_assessed",
            project_id=project_id,
            sub_hypothesis_id=source_sub_hypothesis_id,
            paper_id=record_payload.get("paper_id"),
            status=foundation_context_admission["status"],
            admitted=bool(foundation_context_admission.get("admitted")),
            reason=str(foundation_context_admission.get("reason") or ""),
        )
    if retrieval_branch:
        evidence_payload["retrieval_branch"] = retrieval_branch
    project.setdefault("papergraph", []).append(record_payload)
    project.setdefault("evidence", []).append(evidence_payload)
    project["updatedAt"] = time.time()
    if identity_index is not None:
        register_project_paper_identity(identity_index, record_payload)
    if save:
        save_project(project)
    log_event(
        "SCIENCE",
        "paper_imported",
        project_id=project_id,
        sub_hypothesis_id=source_sub_hypothesis_id,
        paper_id=record.paper_id,
        title=str(title or "")[:120],
        search_id=normalized_import_context.get("search_id", ""),
        result_index=normalized_import_context.get("result_index", ""),
        layer=normalized_import_context.get("stratified_layer", ""),
        query_branch=normalized_import_context.get("query_branch", ""),
        admission_scope=admission_scope,
        corpus_admitted=corpus_admitted,
        corpus_admission_reason=corpus_admission_reason,
        evidence_role=evidence_role,
        evidence_polarity=evidence_polarity,
        demotion_reason=str(record_payload.get("demotion_reason") or ""),
        relatedness_axes=list(record_payload.get("relatedness_axes") or []),
        missing_contract_requirements=list(
            record_payload.get("missing_contract_requirements") or []
        ),
        next_use=str(record_payload.get("next_use") or ""),
        counts_toward_gate=counts_toward_gate,
        counts_toward_corpus_target=counts_toward_corpus_target,
        sh_locality_scope=sh_locality_scope,
        project_background_only=project_background_only,
        excluded_from_sh_gap_synthesis=project_background_only,
        project_background_reason=project_background_reason,
        policy_economic_context=policy_economic_context,
        policy_economic_context_hits=policy_economic_context_hits,
        policy_economic_context_demoted=policy_economic_context_demoted,
        policy_economic_demoted_scope=policy_economic_demoted_scope,
        sh_declares_policy_economic_endpoint=sh_declares_policy_economic_endpoint,
        sh_policy_economic_axis_hits=sh_policy_economic_axis_hits,
        counts_toward_component_bridge_gap=counts_toward_component_bridge_gap,
        corpus_evidence_tier=corpus_evidence_tier,
        gate_counting_evidence=gate_counting_evidence,
        auxiliary_eligible=bool(record_payload.get("auxiliary_eligible")),
        core_eligible=core_eligible_for_log,
        standard_core_eligible=standard_core_eligible_for_log,
        fulltext_acquired=full_text_available,
        fulltext_structurally_usable=bool(full_text_available),
        fulltext_evidence_admissible=bool(full_text_available),
        provider=provider,
        source_type=source_type,
        credibility=score,
        evidence_kind=evidence_kind,
        alignment_verdict=(alignment_assessment or {}).get("verdict", ""),
        foundational_bridge=bool(foundational_bridge_assessment),
        paper_genre=genre_assessment.get("genre", ""),
        visual_evidence_count=int(initial_visual_summary.get("total") or 0),
        visual_component_bridge_candidates=int(
            initial_visual_summary.get("visual_component_bridge_candidate") or 0
        ),
        visual_core_candidates_pending_review=int(
            initial_visual_summary.get("visual_core_candidate_pending_review") or 0
        ),
        visual_evidence_counts_toward_gate=False,
    )
    if initial_visual_evidence:
        log_event(
            "SCIENCE",
            "visual_evidence_imported",
            project_id=project_id,
            sub_hypothesis_id=source_sub_hypothesis_id,
            paper_id=record.paper_id,
            visual_evidence_count=int(initial_visual_summary.get("total") or 0),
            admission_summary=dict(initial_visual_summary),
            counts_toward_gate=False,
            requires_human_review=True,
        )
    log_event(
        "SCIENCE",
        "candidate_imported",
        project_id=project_id,
        sub_hypothesis_id=source_sub_hypothesis_id,
        paper_id=record.paper_id,
        title=str(title or "")[:120],
        search_id=normalized_import_context.get("search_id", ""),
        result_index=normalized_import_context.get("result_index", ""),
        layer=normalized_import_context.get("stratified_layer", ""),
        selection_stage=normalized_import_context.get(
            "selection_stage",
            "pre_import",
        ),
        candidate_research_role=normalized_import_context.get(
            "candidate_research_role",
            "",
        ),
        targeted_admission_tier=normalized_import_context.get(
            "targeted_admission_tier",
            "",
        ),
        provisional_evidence_lane=normalized_import_context.get(
            "provisional_evidence_lane",
            "",
        ),
        detail_revalidation_required=bool(
            normalized_import_context.get("detail_revalidation_required")
        ),
        final_research_role=str(record_payload.get("research_role") or ""),
        admission_scope=admission_scope,
        core_eligible=core_eligible_for_log,
        standard_core_eligible=standard_core_eligible_for_log,
        sh_locality_scope=sh_locality_scope,
        project_background_only=project_background_only,
        project_background_reason=project_background_reason,
        policy_economic_context=policy_economic_context,
        policy_economic_context_hits=policy_economic_context_hits,
        policy_economic_context_demoted=policy_economic_context_demoted,
        policy_economic_demoted_scope=policy_economic_demoted_scope,
        sh_declares_policy_economic_endpoint=sh_declares_policy_economic_endpoint,
        fulltext_acquired=full_text_available,
    )
    return json.dumps(
        {
            "status": "imported",
            "record": record_payload,
        },
        ensure_ascii=False,
        indent=2,
    )


def domain_review_paper(
    project_id: str,
    paper_id: str,
    target_domain_profile: list[str] | str | None = None,
    min_confidence: float = 0.6,
) -> dict[str, Any]:
    """Audit one imported record and deactivate only clear domain mismatches."""
    try:
        from ._literature_scoring import domain_review_assessment
        from ._project import load_project, load_search, save_project
        from ._utils import find_by_id, normalize_space
    except ImportError:
        from _literature_scoring import domain_review_assessment
        from _project import load_project, load_search, save_project
        from _utils import find_by_id, normalize_space
    project = load_project(project_id)
    paper = find_by_id(project.get("papergraph", []), "paper_id", paper_id)
    if not isinstance(paper, dict):
        return {"status": "not_found", "paper_id": paper_id}
    if isinstance(target_domain_profile, list):
        target_domain = normalize_space(" ".join(str(item) for item in target_domain_profile if str(item).strip()))
    else:
        target_domain = normalize_space(str(target_domain_profile or project.get("domain") or ""))
    import_context = paper.get("import_context") if isinstance(paper.get("import_context"), dict) else {}
    retrieval_query = normalize_space(str(paper.get("retrieval_query") or import_context.get("retrieval_query") or ""))
    review_input = dict(paper)
    if not isinstance(review_input.get("domain_relevance"), dict) and import_context.get("search_id") is not None:
        try:
            search_record = load_search(str(import_context.get("search_id") or ""))
            result_index = int(import_context.get("result_index") or 0)
            search_results = search_record.get("results") if isinstance(search_record.get("results"), list) else []
            source_result = search_results[result_index] if 0 <= result_index < len(search_results) else {}
            if isinstance(source_result, dict):
                source_relevance = source_result.get("domain_relevance")
                if isinstance(source_relevance, dict):
                    review_input["domain_relevance"] = dict(source_relevance)
                    paper["domain_relevance"] = dict(source_relevance)
                source_gate = source_result.get("domain_gate")
                if isinstance(source_gate, dict):
                    paper["domain_gate"] = dict(source_gate)
                retrieval_query = retrieval_query or normalize_space(str(search_record.get("query") or ""))
                if retrieval_query:
                    paper["retrieval_query"] = retrieval_query
        except Exception as exc:
            log_event(
                "WARN",
                "domain_review_provenance_recovery_failed",
                project_id=project_id,
                paper_id=paper_id,
                error=str(exc)[:200],
            )
    review = domain_review_assessment(
        review_input,
        domain=target_domain,
        query=retrieval_query,
        min_confidence=min_confidence,
    )
    domain_override = paper.get("domain_override") if isinstance(paper.get("domain_override"), dict) else {}
    if domain_override.get("force_import") and review.get("verdict") == "reject":
        review["original_verdict"] = "reject"
        review["verdict"] = "review"
        review["forced_by_user"] = True
        review["reason"] = "User-forced import retained despite a domain-review rejection; keep it marked for human review."
    review.update({
        "paper_id": paper_id,
        "title": str(paper.get("title") or ""),
        "target_domain": target_domain,
        "reviewedAt": time.time(),
    })
    active = review.get("verdict") != "reject"
    paper["active"] = active
    paper["domain_review"] = review
    paper["domain_review_verdict"] = review.get("verdict")
    paper["domain_review_score"] = review.get("score")
    for evidence in project.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        if evidence.get("paper_id") == paper_id or (
            str(evidence.get("citation") or "") and str(evidence.get("citation") or "") == str(paper.get("citation") or "")
        ):
            evidence["active"] = active
    project.setdefault("domain_reviews", {})[paper_id] = review
    save_project(project)
    if not active:
        log_event(
            "SCIENCE",
            "paper_domain_rejected",
            project_id=project_id,
            paper_id=paper_id,
            title=str(paper.get("title") or "")[:120],
            score=review.get("score"),
            reason=review.get("reason"),
        )
    return review


def review_imported_papers_for_domain(
    project_id: str,
    paper_ids: list[str],
    target_domain_profile: list[str] | str | None = None,
    min_confidence: float = 0.6,
) -> list[dict[str, Any]]:
    """Run the same domain audit across an import batch for ZhiZhi."""
    reviews: list[dict[str, Any]] = []
    for paper_id in dict.fromkeys(str(item) for item in paper_ids if str(item).strip()):
        reviews.append(
            domain_review_paper(
                project_id=project_id,
                paper_id=paper_id,
                target_domain_profile=target_domain_profile,
                min_confidence=min_confidence,
            )
        )
    return reviews


def reconcile_project_domain_reviews(
    project_id: str,
    target_domain_profile: list[str] | str | None = None,
    min_confidence: float = 0.6,
    include_active: bool = False,
) -> str:
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    records = [record for record in project.get("papergraph", []) if isinstance(record, dict)]
    prior_active = {str(record.get("paper_id") or ""): bool(record.get("active", True)) for record in records}
    paper_ids = [
        str(record.get("paper_id") or "")
        for record in records
        if include_active or not bool(record.get("active", True))
    ]
    reviews = review_imported_papers_for_domain(
        project_id=project_id,
        paper_ids=paper_ids,
        target_domain_profile=target_domain_profile,
        min_confidence=min_confidence,
    )
    reactivated = [
        review for review in reviews
        if review.get("verdict") != "reject" and not prior_active.get(str(review.get("paper_id") or ""), True)
    ]
    return json.dumps(
        {
            "project_id": project_id,
            "reviewed_count": len(reviews),
            "reactivated_count": len(reactivated),
            "remaining_rejected_count": sum(1 for review in reviews if review.get("verdict") == "reject"),
            "review_count": sum(1 for review in reviews if review.get("verdict") == "review"),
            "reactivated": reactivated,
            "reviews": reviews,
            "next_step": "Inspect review-status records before using them as high-confidence causal evidence.",
        },
        ensure_ascii=False,
        indent=2,
    )

def extract_paper_keynote(
    project_id: str,
    paper_id: str = "",
    search_id: str = "",
    result_index: int = 0,
    text: str = "",
    use_llm: bool = True,
) -> str:
    try:
        from ._project import load_project, load_search, save_project
        from ._utils import find_by_id, new_id
    except ImportError:
        from _project import load_project, load_search, save_project
        from _utils import find_by_id, new_id
    project = load_project(project_id)
    source: dict[str, Any] = {}
    source_text = text
    if paper_id:
        source = find_by_id(project.get("papergraph", []), "paper_id", paper_id) or {}
        if not source:
            raise ValueError(f"Paper not found in project PaperGraph: {paper_id}")
        source_text = "\n\n".join(
            part for part in [source.get("title", ""), source.get("abstract", ""), source.get("conclusion", ""), source.get("contribution", ""), source.get("limitation", ""), source.get("full_text_excerpt", "")] if part
        )
    elif search_id:
        search_record = load_search(search_id)
        results = search_record.get("results", [])
        try:
            source = results[int(result_index)]
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid search result {search_id}:{result_index}") from exc
        source_text = "\n\n".join(part for part in [source.get("title", ""), source.get("abstract", "")] if part)
    elif not source_text:
        raise ValueError("Provide paper_id, search_id/result_index, or text.")

    if use_llm:
        try:
            keynote = extract_keynote_with_llm(source_text)
            keynote["status"] = "KEYNOTE_READY"
            keynote["extractor"] = f"{SCIENCE_LLM_EXTRACTOR}_json"
            keynote["reason_codes"] = []
        except Exception as exc:
            log_event("WARN", "keynote_llm_failed", error=str(exc))
            keynote = {
                "status": "LLM_EXTRACTION_PENDING",
                "extractor": "llm_pending",
                "reason_codes": [f"LLM_KEYNOTE_EXTRACTION_PENDING:{type(exc).__name__}"],
                "llm_error": str(exc),
                "title": "",
                "core_problem": "",
                "contributions": [],
                "methods": [],
                "experiments_or_evidence": [],
                "assumptions": [],
                "limitations": [],
                "gap_signals": [],
                "datasets_or_materials": [],
                "code_or_implementation": [],
                "important_claims": [],
                "causal_chains": [],
                "reuse_value_for_research": "",
            }
    else:
        keynote = {
            "status": "LLM_DISABLED",
            "extractor": "llm_disabled",
            "reason_codes": ["LLM_KEYNOTE_EXTRACTION_DISABLED"],
            "title": "",
            "core_problem": "",
            "contributions": [],
            "methods": [],
            "experiments_or_evidence": [],
            "assumptions": [],
            "limitations": [],
            "gap_signals": [],
            "datasets_or_materials": [],
            "code_or_implementation": [],
            "important_claims": [],
            "causal_chains": [],
            "reuse_value_for_research": "",
        }

    item = {
        "keynote_id": new_id("keynote"),
        "paper_id": paper_id,
        "search_id": search_id,
        "result_index": result_index if search_id else None,
        "title": source.get("title", keynote.get("title", "")),
        "createdAt": time.time(),
        "keynote": keynote,
    }
    project.setdefault("keynotes", []).append(item)
    if paper_id and isinstance(source, dict):
        source["causal_chains"] = normalize_causal_chains(
            keynote.get("causal_chains") or source.get("causal_chains") or []
        )
    save_project(project)
    return json.dumps(item, ensure_ascii=False, indent=2)

def list_papergraph_records(project_id: str) -> str:
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    records = project.get("papergraph", [])
    if not records:
        return "(no PaperGraph records)"
    lines = []
    for record in records:
        lines.append(
            f"{record.get('paper_id')} score={record.get('credibility_score')} "
            f"{record.get('citation')} - {record.get('title')}"
        )
    return "\n".join(lines)

def repair_payload_fields(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import first_sentences, is_unknown_value, record_context_text
    except ImportError:
        from _utils import first_sentences, is_unknown_value, record_context_text
    context_text = record_context_text(payload)
    repaired = dict(payload)
    repaired = repair_method_scenario_benchmark_fields(repaired)
    if is_unknown_value(repaired.get("contribution")):
        repaired["contribution"] = first_sentences(context_text, 1)
    if is_unknown_value(repaired.get("limitation")):
        repaired["limitation"] = "No explicit limitation extracted."
    return repaired


_MSB_DESCRIPTOR_FIELDS = ("method", "scenario", "benchmark")
_MSB_DESCRIPTOR_LIMITS = {
    "method": {"characters": 96, "words": 12},
    "scenario": {"characters": 120, "words": 16},
    "benchmark": {"characters": 96, "words": 12},
}
_MSB_GENERIC_DESCRIPTORS = {
    "method": {
        "analysis", "approach", "assay", "experiment", "framework", "method", "methods",
        "methodology", "model", "models", "protocol", "review", "study", "studies",
        "technique", "validation",
    },
    "scenario": {
        "application", "case", "cohort", "data set", "dataset", "domain", "environment",
        "experimental conditions", "mice", "mouse", "natural conditions", "patient", "patients",
        "population", "sample", "samples", "setting", "system", "systems", "task",
    },
    "benchmark": {
        "accuracy", "benchmark", "benchmark data", "benchmark dataset", "effect size", "endpoint",
        "index", "metric", "p value", "p-value", "performance", "readout", "response", "score",
        "sensitivity", "statistical significance", "throughput", "toxicity", "validation", "yield",
    },
}
_MSB_BOILERPLATE_MARKERS = (
    "all rights reserved", "copyright", "creative commons", "doi:", "http://", "https://",
    "open access article", "open-access article", "public domain", "repository", "www.",
)
_MSB_NARRATIVE_MARKERS = (
    " is estimated", " are estimated", " remains ", " remain ", " was estimated",
    " were estimated", " has been ", " have been ", " this study", " this paper",
)
_MSB_GENERIC_ONTOLOGY_TERMS = {
    "analysis", "application", "case", "cohort", "condition", "dataset", "environment", "model",
    "patient", "patients", "performance", "safety", "sample", "system", "therapy", "validation",
}
_MSB_METHOD_CUES = (
    "ablation", "administration", "algorithm", "analysis", "assay", "assisted", "atac-seq",
    "case-control", "characterization", "classification", "clinical trial", "cohort", "crispr",
    "culture", "design", "dynamics", "elisa", "experiment", "exposure", "field", "fitting",
    "imaging", "inference", "intervention", "laboratory", "lineage tracing", "measurement",
    "microscopy", "model", "modelling", "modeling", "nmr", "observation", "pcr", "profiling",
    "perturbation", "quantification", "regression", "rna-seq", "screening", "sequencing", "simulation", "spectroscopy",
    "synthesis", "tomography", "transplant", "western blot",
)


def authoritative_descriptor_source_text(record: dict[str, Any]) -> str:
    """Return the only source text permitted to support an M-S-B descriptor.

    Full-text excerpts frequently contain OCR, license, citation, and reference-list
    fragments.  They can still inform human review, but must not self-validate a
    structured method, scenario, or benchmark used for graph construction.
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    return "\n".join(
        normalize_space(str(record.get(field) or ""))
        for field in ("title", "abstract", "conclusion")
        if normalize_space(str(record.get(field) or ""))
    )


def _descriptor_content_tokens(value: str) -> list[str]:
    stop_words = {
        "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with",
    }
    return [
        token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", value.lower())
        if len(token) > 1 and token not in stop_words
    ]


def _descriptor_looks_malformed(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _MSB_BOILERPLATE_MARKERS):
        return True
    if re.search(r"(?:\b[a-z]\s+){6,}[a-z]\b", value, flags=re.IGNORECASE):
        return True
    if re.search(r"[a-z]{28,}", value, flags=re.IGNORECASE):
        return True
    if sum(1 for char in value if char.isalpha()) >= 12:
        letters = [char for char in value if char.isalpha()]
        vowel_ratio = sum(char.lower() in "aeiou" for char in letters) / max(1, len(letters))
        if vowel_ratio < 0.12:
            return True
    return False


def _ontology_descriptor_support(value: str, field: str, lowered_source: str) -> bool:
    """Accept a canonical ontology label only when a specific source cue supports it."""
    try:
        from ._models import BENCHMARK_ONTOLOGY, METHOD_ONTOLOGY, SCENARIO_ONTOLOGY
        from ._utils import normalize_label, science_term_in_text
    except ImportError:
        from _models import BENCHMARK_ONTOLOGY, METHOD_ONTOLOGY, SCENARIO_ONTOLOGY
        from _utils import normalize_label, science_term_in_text
    ontology = {
        "method": METHOD_ONTOLOGY,
        "scenario": SCENARIO_ONTOLOGY,
        "benchmark": BENCHMARK_ONTOLOGY,
    }.get(field, {})
    normalized_value = normalize_label(value).lower()
    patterns = ontology.get(normalized_value, [])
    if not patterns:
        return False
    for pattern in patterns:
        normalized_pattern = normalize_label(pattern).lower()
        if not science_term_in_text(normalized_pattern, lowered_source):
            continue
        pattern_tokens = _descriptor_content_tokens(normalized_pattern)
        if len(pattern_tokens) >= 2:
            return True
        if pattern_tokens and pattern_tokens[0] not in _MSB_GENERIC_ONTOLOGY_TERMS:
            return True
    return False


def assess_structured_descriptor(value: Any, field: str, source_text: str) -> dict[str, Any]:
    """Assess a method/scenario/benchmark before it can enter a graph or gap path."""
    try:
        from ._utils import is_unknown_value, normalize_label, normalize_space, science_term_in_text
    except ImportError:
        from _utils import is_unknown_value, normalize_label, normalize_space, science_term_in_text
    normalized_field = str(field or "").strip().lower()
    normalized_value = normalize_label(value)
    assessment = {
        "accepted": False,
        "field": normalized_field,
        "value": normalized_value,
        "reason": "",
        "source_support": "none",
    }
    if normalized_field not in _MSB_DESCRIPTOR_FIELDS:
        assessment["reason"] = "unsupported_descriptor_field"
        return assessment
    if is_unknown_value(normalized_value):
        assessment["reason"] = "unknown_or_empty"
        return assessment
    lowered_value = normalize_space(normalized_value).lower()
    assessment["value"] = lowered_value
    limits = _MSB_DESCRIPTOR_LIMITS[normalized_field]
    if len(lowered_value) > limits["characters"] or len(lowered_value.split()) > limits["words"]:
        assessment["reason"] = "descriptor_too_long"
        return assessment
    if _descriptor_looks_malformed(lowered_value):
        assessment["reason"] = "malformed_or_boilerplate"
        return assessment
    if lowered_value in _MSB_GENERIC_DESCRIPTORS[normalized_field] or is_low_information_field(lowered_value, normalized_field):
        assessment["reason"] = "schema_generic_descriptor"
        return assessment
    if any(marker in f" {lowered_value} " for marker in _MSB_NARRATIVE_MARKERS):
        assessment["reason"] = "narrative_fragment"
        return assessment
    if normalized_field == "method" and not any(cue in lowered_value for cue in _MSB_METHOD_CUES):
        assessment["reason"] = "not_method_shaped"
        return assessment
    lowered_source = normalize_space(source_text).lower()
    if not lowered_source:
        assessment["reason"] = "missing_authoritative_source"
        return assessment
    if science_term_in_text(lowered_value, lowered_source):
        assessment.update(accepted=True, reason="", source_support="exact_phrase")
        return assessment
    value_tokens = _descriptor_content_tokens(lowered_value)
    supported_tokens = [token for token in value_tokens if science_term_in_text(token, lowered_source)]
    if len(value_tokens) >= 2 and len(supported_tokens) == len(value_tokens):
        assessment.update(accepted=True, reason="", source_support="token_coverage")
        return assessment
    if _ontology_descriptor_support(lowered_value, normalized_field, lowered_source):
        assessment.update(accepted=True, reason="", source_support="ontology_match")
        return assessment
    assessment["reason"] = "source_unsupported"
    return assessment


def repair_method_scenario_benchmark_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Repair only from title/abstract/conclusion and leave an explicit audit trail."""
    try:
        from ._utils import normalize_label, unique_preserve_order
    except ImportError:
        from _utils import normalize_label, unique_preserve_order
    repaired = dict(payload)
    source_text = authoritative_descriptor_source_text(repaired)
    quality = dict(repaired.get("extraction_quality") or {})
    existing_flags = quality.get("flags") if isinstance(quality.get("flags"), list) else []
    flags = list(existing_flags)
    admissions: dict[str, dict[str, Any]] = {}
    for field in _MSB_DESCRIPTOR_FIELDS:
        original = repaired.get(field, "")
        assessment = assess_structured_descriptor(original, field, source_text)
        replacement = ""
        replacement_assessment: dict[str, Any] | None = None
        if not assessment["accepted"]:
            inferred = infer_ontology_field(source_text, field)
            if inferred and normalize_label(inferred).lower() != normalize_label(original).lower():
                replacement_assessment = assess_structured_descriptor(inferred, field, source_text)
                if replacement_assessment["accepted"]:
                    replacement = str(replacement_assessment["value"])
            if replacement:
                repaired[field] = replacement
                admissions[field] = {
                    **replacement_assessment,
                    "repaired_from": normalize_label(original),
                    "repair_reason": assessment["reason"],
                }
                flags.append(f"{field}_source_repaired")
            else:
                repaired[field] = f"unknown {field}"
                admissions[field] = assessment
                flags.append(f"{field}_{assessment['reason']}")
                quality["requires_human_review"] = True
        else:
            repaired[field] = str(assessment["value"])
            admissions[field] = assessment
    quality["flags"] = unique_preserve_order(flags)
    quality["msb_descriptor_admission"] = admissions
    quality["msb_descriptor_source"] = "title_abstract_conclusion_only"
    repaired["extraction_quality"] = quality
    return repaired


def repair_unsupported_scenario(payload: dict[str, Any], context_text: str) -> dict[str, Any]:
    return repair_method_scenario_benchmark_fields(payload)

def scenario_is_supported_by_context(scenario: str, lowered_context: str) -> bool:
    try:
        from ._literature_search import query_terms
        from ._models import SCENARIO_ONTOLOGY
        from ._utils import science_term_in_text
    except ImportError:
        from _literature_search import query_terms
        from _models import SCENARIO_ONTOLOGY
        from _utils import science_term_in_text
    scenario_terms = query_terms(scenario)
    if not scenario_terms:
        return False
    hits = [term for term in scenario_terms if science_term_in_text(term, lowered_context)]
    if hits:
        return True
    ontology_terms = SCENARIO_ONTOLOGY.get(scenario, [])
    return any(science_term_in_text(str(term), lowered_context) for term in ontology_terms)

def sync_evidence_from_record(project: dict[str, Any], record: dict[str, Any]) -> None:
    evidence_items = project.get("evidence", [])
    if not isinstance(evidence_items, list):
        return
    citation = str(record.get("citation") or "")
    title = str(record.get("title") or "")
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            continue
        if (citation and evidence.get("citation") == citation) or (title and evidence.get("title") == title):
            evidence["method"] = record.get("method", evidence.get("method", ""))
            evidence["scenario"] = record.get("scenario", evidence.get("scenario", ""))
            evidence["benchmark"] = record.get("benchmark", evidence.get("benchmark", ""))
            evidence["contribution"] = record.get("contribution", evidence.get("contribution", ""))
            evidence["limitation"] = record.get("limitation", evidence.get("limitation", ""))


def restrict_candidate_only_document_genre(
    genre_assessment: dict[str, Any],
    evidence_admission: dict[str, Any],
) -> dict[str, Any]:
    """Keep OCR/supplement text discoverable without admitting it as direct evidence."""
    restricted = dict(genre_assessment or {})
    restricted["direct_theoretical_evidence"] = False
    restricted["direct_experimental_evidence"] = False
    restricted["conversion_evidence_admission"] = "candidate_only"
    restricted["conversion_evidence_reason"] = str(evidence_admission.get("reason") or "")
    maturity = dict(restricted.get("evidence_maturity") or {})
    maturity["automatic_l1_acceptance"] = False
    maturity["conversion_candidate_only"] = True
    restricted["evidence_maturity"] = maturity
    return restricted

def verify_citation_uniqueness(
    project_id: str,
    title: str = "",
    citation: str = "",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    url: str = "",
) -> str:
    try:
        from ._literature_search import search_literature
        from ._project import load_project, save_project
    except ImportError:
        from _literature_search import search_literature
        from _project import load_project, save_project
    project = load_project(project_id)
    unique_key = paper_unique_key(title=title, citation=citation, doi=doi, arxiv_id=arxiv_id, semantic_scholar_id=semantic_scholar_id, url=url)
    duplicates = [record for record in project.get("papergraph", []) if record.get("unique_key") == unique_key]
    checks = project.setdefault("citation_uniqueness_checks", [])
    prior_count = sum(1 for item in checks if isinstance(item, dict) and item.get("unique_key") == unique_key)
    result = {
        "unique": not duplicates,
        "unique_key": unique_key,
        "duplicates": duplicates,
        "repeated_check": prior_count > 0,
        "prior_check_count": prior_count,
        "next_step": (
            "This citation has already been checked in this run; do not repeat verify_citation_uniqueness. "
            "If it is unique, import only if it came from a real cached search result; otherwise continue with search_literature/select/import."
            if prior_count > 0
            else "Use this uniqueness result once. Do not repeatedly call verify_citation_uniqueness for the same citation."
        ),
    }
    checks.append(
        {
            "unique_key": unique_key,
            "title": title,
            "citation": citation,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "semantic_scholar_id": semantic_scholar_id,
            "url": url,
            "unique": not duplicates,
            "checkedAt": time.time(),
        }
    )
    if len(checks) > 200:
        project["citation_uniqueness_checks"] = checks[-200:]
    project["updatedAt"] = time.time()
    save_project(project)
    return json.dumps(result, ensure_ascii=False, indent=2)

def parse_literature_text(text: str, use_llm: bool | None = None) -> str:
    return json.dumps(extract_paper_structure(text, use_llm=use_llm), ensure_ascii=False, indent=2)

def extract_paper_structure(text: str, use_llm: bool | None = None) -> dict[str, Any]:
    try:
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _science_execution_policy import resolve_science_execution_policy
    policy = resolve_science_execution_policy({}, use_llm=use_llm)
    if not policy.use_llm:
        return _unavailable_paper_structure(
            status="LLM_DISABLED",
            extractor="llm_disabled",
            reason_code="LLM_PAPER_STRUCTURE_EXTRACTION_DISABLED",
        )
    try:
        llm = extract_paper_structure_with_llm(text)
    except Exception as exc:
        log_event("WARN", "paper_llm_extract_failed", error=str(exc))
        return _unavailable_paper_structure(
            status="LLM_EXTRACTION_PENDING",
            extractor="llm_pending",
            reason_code=f"LLM_PAPER_STRUCTURE_EXTRACTION_PENDING:{type(exc).__name__}",
            error=str(exc),
        )
    structured = apply_paper_role_exclusivity(dict(llm))
    structured["status"] = "STRUCTURED_BY_LLM"
    structured["extractor"] = f"{SCIENCE_LLM_EXTRACTOR}_json"
    structured["reason_codes"] = []
    return structured


def _unavailable_paper_structure(
    *,
    status: str,
    extractor: str,
    reason_code: str,
    error: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "extractor": extractor,
        "reason_codes": [reason_code],
        "llm_error": error,
        "title": "",
        "citation": "",
        "authors": [],
        "year": "",
        "venue": "",
        "doi": "",
        "arxiv_id": "",
        "abstract": "",
        "conclusion": "",
        "strengths": [],
        "improvements": [],
        "method": "",
        "scenario": "",
        "benchmark": "",
        "contribution": "",
        "limitation": "",
        "causal_chains": [],
        "gap_signals": [],
        "eligible_for_evidence_admission": False,
    }


_PAPER_CONTEXT_HEADINGS = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*|(?:\d+(?:\.\d+)*[.)]?\s+))?"
    r"(abstract|summary|introduction|background|materials?\s+and\s+methods?|"
    r"methods?|methodology|experimental(?:\s+methods?)?|results?|findings|"
    r"discussion|conclusions?|limitations?|future\s+work|outlook)\b[^\n]*$"
)


def select_paper_structure_context(
    text: str,
    *,
    max_units: int = SCIENCE_LLM_PAPER_CONTEXT_UNITS,
) -> str:
    """Select auditable reading fragments across a long paper for one LLM call.

    The complete Markdown remains in ``full_text_excerpt``.  This function only
    limits a model request, retaining the beginning/end and recognized scientific
    sections instead of silently passing an arbitrary prefix of a long PDF.
    """
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source or _estimate_context_units(source) <= max_units:
        return source

    source_length = len(source)
    candidates: list[tuple[int, int, int, str]] = [
        (0, min(source_length, 3_600), 100, "opening metadata and abstract"),
        (max(0, source_length - 4_200), source_length, 95, "closing discussion and conclusion"),
    ]
    for match in _PAPER_CONTEXT_HEADINGS.finditer(source):
        heading = " ".join(match.group(1).split()).lower()
        priority = 92 if heading in {"abstract", "summary", "conclusion", "conclusions", "limitations", "future work", "outlook"} else 82
        candidates.append(
            (match.start(), min(source_length, match.start() + 5_200), priority, heading)
        )

    # Some converted articles lack reliable headings.  These compact samples
    # retain document-wide coverage without making a single model request carry
    # every extracted character.
    for fraction in (0.18, 0.38, 0.50, 0.58, 0.78):
        start = int(source_length * fraction)
        candidates.append(
            (start, min(source_length, start + 2_200), 25, "document-wide sample")
        )

    selected: list[tuple[int, int, int, str]] = []
    selected_by_label: dict[str, int] = {}
    for start, end, priority, label in sorted(candidates, key=lambda item: (-item[2], item[0])):
        if priority >= 80 and selected_by_label.get(label, 0) >= 2:
            continue
        start, end = _expand_context_bounds(source, start, end)
        if end <= start:
            continue
        overlap = sum(
            max(0, min(end, current_end) - max(start, current_start))
            for current_start, current_end, _, _ in selected
        )
        if overlap / max(1, end - start) >= 0.62:
            continue
        selected.append((start, end, priority, label))
        selected_by_label[label] = selected_by_label.get(label, 0) + 1

    # A malformed conversion can emit many repeated pseudo-headings.  Preserve
    # the most informative fragments while keeping enough model budget for each
    # one, rather than assembling a huge context and then clipping its middle.
    selected = sorted(selected, key=lambda item: (-item[2], item[0]))[:20]
    selected.sort(key=lambda item: item[0])
    if not selected:
        return _clip_context_units(source, max_units)

    separator = "\n\n---\n\n"
    fixed_units = sum(
        _estimate_context_units(f"[Selected full-text fragment: {label}]\n\n")
        for _, _, _, label in selected
    ) + _estimate_context_units(separator) * max(0, len(selected) - 1)
    content_units = max(1, max_units - fixed_units)
    per_fragment_units = max(1, min(1_800, content_units // len(selected)))
    fragments = [
        "\n\n".join(
            (
                f"[Selected full-text fragment: {label}]",
                _clip_context_units(source[start:end].strip(), per_fragment_units),
            )
        )
        for start, end, _, label in selected
    ]
    context = separator.join(fragment for fragment in fragments if fragment)
    # The construction above accounts for all fixed labels and fragment units;
    # retain this fallback for future format changes that add prompt markers.
    return _clip_context_units(context, max_units)


def _expand_context_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Move fragment boundaries to blank-line edges where practical."""
    left = text.rfind("\n\n", max(0, start - 700), start)
    right = text.find("\n\n", end, min(len(text), end + 1_200))
    return (left + 2 if left >= 0 else start, right if right >= 0 else end)


def _estimate_context_units(text: str) -> int:
    cjk_or_fullwidth = sum(1 for char in str(text or "") if ord(char) >= 0x2E80)
    other = len(str(text or "")) - cjk_or_fullwidth
    return cjk_or_fullwidth + (other + 3) // 4


def _take_context_units(text: str, budget_units: int) -> str:
    consumed = 0.0
    for index, char in enumerate(text, start=1):
        char_units = 1.0 if ord(char) >= 0x2E80 else 0.25
        if consumed + char_units > budget_units:
            return text[: index - 1]
        consumed += char_units
    return text


def _clip_context_units(text: str, budget_units: int) -> str:
    if _estimate_context_units(text) <= budget_units:
        return text
    marker = "\n[... full-text fragment shortened for this model request ...]\n"
    usable = max(1, budget_units - _estimate_context_units(marker))
    prefix = _take_context_units(text, max(1, usable * 3 // 5))
    suffix_budget = max(1, usable - _estimate_context_units(prefix))
    suffix = _take_context_units(text[::-1], suffix_budget)[::-1]
    return prefix + marker + suffix

def extract_paper_structure_with_llm(text: str) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json, normalize_llm_paper_structure
    except ImportError:
        from _llm import call_llm_json, normalize_llm_paper_structure
    schema = {
        "title": "string",
        "citation": "string",
        "authors": ["string"],
        "year": "string",
        "venue": "string",
        "doi": "string",
        "arxiv_id": "string",
        "abstract": "string",
        "conclusion": "string",
        "strengths": ["string"],
        "improvements": ["string"],
        "method": "string",
        "scenario": "string",
        "benchmark": "string",
        "contribution": "string",
        "limitation": "string",
        "causal_chains": [
            {
                "chain_id": "string",
                "trigger": "string",
                "trigger_evidence": "short source-grounded excerpt",
                "steps": [{"claim": "string", "evidence": "short source-grounded excerpt", "evidence_type": "experimental | theoretical | observational | inferred"}],
                "outcome": "string",
                "outcome_evidence": "short source-grounded excerpt",
                "context": {"research_object": "string", "species_or_system": "string", "model_or_sample": "string", "stage_or_regime": "string", "timepoint": "string"},
                "observables": ["measured signal"],
                "interventions": ["manipulated condition"],
                "confidence": 0.0,
            }
        ],
        "gap_signals": [{"signal_type": "limitation | future_work | open_problem | challenge | missing_evidence", "text": "string"}],
    }
    payload = call_llm_json(
        system="You are PaperGraph Extractor. You produce valid compact JSON only.",
        max_tokens=2500,
        prompt=(
            "Extract a scientific paper into strict JSON. Return JSON only, no markdown. "
            "Use empty strings or empty arrays when unavailable. Preserve factual wording; do not invent citations.\n\n"
            "General extraction rules:\n"
            "- method: the concrete research method, instrument, index, model, algorithm, experimental design, synthesis route, assay, or analysis approach actually used by the paper. "
            "Do not use a background sentence, research motivation, or broad topic as the method.\n"
            "- scenario: the scientific system, task, phenomenon, application setting, material class, organism/disease, environment, engineering system, or domain where the method is applied.\n"
            "- benchmark: the evaluated metric, observable, endpoint, dataset, response variable, performance criterion, experimental readout, or validation target.\n"
            "- contribution: the paper's main supported finding or methodological advance.\n"
            "- limitation: an explicit limitation, unresolved problem, boundary condition, or future-work point; use an empty string if not stated.\n"
            "- contribution and limitation are mutually exclusive semantic roles. Never copy the same sentence or abstract passage into both.\n"
            "- strengths and improvements must contain distinct, role-specific points. Do not copy an abstract wholesale and do not repeat contribution or limitation verbatim.\n\n"
            "- causal_chains: extract only causal relations that the paper claims or tests. Keep intermediate steps, study context (object, species/system, model/sample, stage/regime), and attach a short source-grounded excerpt to every step when available. "
            "Use experimental, theoretical, observational, or inferred evidence types. Do not convert co-occurrence into causation; return an empty list when a causal chain is unsupported.\n\n"
            "- gap_signals: extract multiple explicit limitations, future-work directions, open problems, unresolved challenges, and missing-evidence statements when present, especially from PDF/full-text discussion, limitations, conclusion, and outlook sections.\n\n"
            "Cross-domain examples for choosing compact labels:\n"
            "- mathematics/statistics: method=theoretical proof | bayesian inference | causal inference; scenario=statistical inference | dynamical system; benchmark=uncertainty | convergence rate | effect size.\n"
            "- physics/astronomy/geoscience: method=spectroscopy | numerical simulation | seismic inversion | observational survey; scenario=quantum materials | astrophysical observation | earthquake and tectonics; benchmark=spectral feature | structural damage | prediction error.\n"
            "- chemistry/materials/engineering: method=organic synthesis | x-ray diffraction | density functional theory | finite element analysis; scenario=catalytic reaction | semiconductor device testing | structural system only when explicitly stated; benchmark=reaction yield | mechanical strength | device lifetime.\n"
            "- biology/agriculture/medicine/ecology: method=genome sequencing | clinical trial | field experiment | species distribution modeling; scenario=genetic disease | crop stress resilience | biodiversity and community ecology; benchmark=gene expression | clinical response | crop yield | species richness.\n"
            "- computer science/AI: method=deep learning model | graph neural network | reinforcement learning | knowledge graph construction; scenario=medical image analysis | software engineering | AI for science; benchmark=accuracy | robustness | latency | benchmark score.\n"
            "- environmental/earth-system studies: method=remote sensing | numerical model ensemble | spatial analysis | event attribution; scenario=extreme events | watershed system | ecosystem response; benchmark=event intensity | spatial extent | model error | recovery time.\n\n"
            "Guardrails:\n"
            "- Prefer concise normalized labels over long sentences.\n"
            "- If a field is not supported by the supplied text, return an empty string rather than guessing.\n"
            "- Avoid cross-domain leakage: only use a specialized metric label when the paper's domain supports it.\n"
            "- Scenario must be supported by title, abstract, conclusion, or paper metadata; never copy a scenario from examples when the paper text does not mention it.\n"
            "- If the abstract is truncated and no concrete method is stated, leave method empty rather than writing a vague phrase.\n\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "Paper text is represented by source fragments selected across the full document. "
            "Treat only the supplied wording as evidence; omitted sections are not evidence.\n\n"
            f"Paper text:\n{select_paper_structure_context(text)}"
        ),
    )
    return normalize_llm_paper_structure(payload)

def extract_keynote_with_llm(text: str) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    schema = {
        "title": "string",
        "core_problem": "string",
        "contributions": ["string"],
        "methods": ["string"],
        "experiments_or_evidence": ["string"],
        "assumptions": ["string"],
        "limitations": ["string"],
        "gap_signals": [{"signal_type": "string", "text": "string"}],
        "datasets_or_materials": ["string"],
        "code_or_implementation": ["string"],
        "important_claims": [{"claim": "string", "evidence": "string"}],
        "causal_chains": [
            {
                "trigger": "string",
                "steps": [{"claim": "string", "evidence": "string", "evidence_type": "experimental | theoretical | observational | inferred"}],
                "outcome": "string",
                "context": {"research_object": "string", "species_or_system": "string", "model_or_sample": "string", "stage_or_regime": "string", "timepoint": "string"},
                "observables": ["string"],
                "interventions": ["string"],
            }
        ],
        "reuse_value_for_research": "string",
    }
    payload = call_llm_json(
        system="You are a DeepSurvey-style keynote reader. Extract grounded, reusable paper notes. JSON only.",
        max_tokens=2500,
        prompt=(
            "Extract a structured keynote for cross-paper comparison. Do not invent facts. "
            "Extract causal chains only when the source supports the stated links. Preserve intermediate steps and evidence excerpts, and do not infer causation from two concepts merely appearing together. "
            "If only abstract is provided, mark missing details as empty arrays.\n\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "Paper text is represented by source fragments selected across the full document. "
            "Treat only the supplied wording as evidence; omitted sections are not evidence.\n\n"
            f"Paper text:\n{select_paper_structure_context(text)}"
        ),
    )
    return normalize_keynote(payload)

def extract_keynote_heuristic(text: str) -> dict[str, Any]:
    try:
        from ._utils import first_sentences, string_list
    except ImportError:
        from _utils import first_sentences, string_list
    parsed = parse_paper_text(text)
    return {
        "title": parsed.get("title", ""),
        "core_problem": first_sentences(parsed.get("abstract", "") or text, 1),
        "contributions": string_list(parsed.get("contribution")),
        "methods": string_list(parsed.get("method")) if parsed.get("method") != "unknown method" else [],
        "experiments_or_evidence": extract_bullets_or_sentences(text, ["experiment", "evaluate", "result", "dataset", "case study"], limit=5),
        "assumptions": extract_bullets_or_sentences(text, ["assume", "assumption", "under the condition"], limit=5),
        "limitations": string_list(parsed.get("limitation")) if parsed.get("limitation") else [],
        "gap_signals": parsed.get("gap_signals", []),
        "datasets_or_materials": extract_bullets_or_sentences(text, ["dataset", "benchmark", "data", "material", "sample"], limit=5),
        "code_or_implementation": extract_bullets_or_sentences(text, ["code", "repository", "implementation", "github"], limit=5),
        "important_claims": [{"claim": parsed.get("contribution", ""), "evidence": parsed.get("abstract", "")} if parsed.get("contribution") else {}],
        "causal_chains": extract_causal_chains_heuristic(text),
        "reuse_value_for_research": "Useful as structured evidence if quality and citation checks pass.",
    }

def normalize_keynote(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import normalize_gap_signals
        from ._utils import scalar, string_list
    except ImportError:
        from _gap_detection import normalize_gap_signals
        from _utils import scalar, string_list
    claims = payload.get("important_claims", [])
    normalized_claims: list[dict[str, str]] = []
    if isinstance(claims, list):
        for item in claims:
            if isinstance(item, dict):
                normalized_claims.append({"claim": scalar(item.get("claim")), "evidence": scalar(item.get("evidence"))})
            elif scalar(item):
                normalized_claims.append({"claim": scalar(item), "evidence": ""})
    return {
        "title": scalar(payload.get("title")),
        "core_problem": scalar(payload.get("core_problem")),
        "contributions": string_list(payload.get("contributions")),
        "methods": string_list(payload.get("methods")),
        "experiments_or_evidence": string_list(payload.get("experiments_or_evidence")),
        "assumptions": string_list(payload.get("assumptions")),
        "limitations": string_list(payload.get("limitations")),
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
        "datasets_or_materials": string_list(payload.get("datasets_or_materials")),
        "code_or_implementation": string_list(payload.get("code_or_implementation")),
        "important_claims": normalized_claims,
        "causal_chains": normalize_causal_chains(payload.get("causal_chains")),
        "reuse_value_for_research": scalar(payload.get("reuse_value_for_research")),
        "extractor": f"{SCIENCE_LLM_EXTRACTOR}_keynote",
    }


def normalize_causal_chains(value: Any) -> list[dict[str, Any]]:
    try:
        from ._llm import normalize_causal_chains as normalize
    except ImportError:
        from _llm import normalize_causal_chains as normalize
    return normalize(value)


def extract_causal_chains_heuristic_legacy(text: str, limit: int = 4) -> list[dict[str, Any]]:
    clean = str(text or "").strip()
    if not clean:
        return []
    markers = r"(?:→|leads to|lead to|causes|cause|drives|results? in|induces|promotes|inhibits|导致|引起|促进|抑制|造成)"
    chains: list[dict[str, Any]] = []
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", clean)
    for sentence in sentences:
        compact = " ".join(sentence.split())
        if len(compact) < 16:
            continue
        match = re.search(rf"(.{{3,220}}?)\s*{markers}\s*(.{{3,220}})", compact, flags=re.IGNORECASE)
        if not match:
            continue
        trigger = match.group(1).strip(" ,;:：，；")
        outcome = match.group(2).strip(" ,;:：，；")
        if not trigger or not outcome:
            continue
        chains.append(
            {
                "chain_id": f"heuristic_{len(chains) + 1}",
                "trigger": trigger,
                "trigger_evidence": compact[:500],
                "steps": [],
                "outcome": outcome,
                "outcome_evidence": compact[:500],
                "observables": [],
                "interventions": [],
                "confidence": 0.3,
            }
        )
        if len(chains) >= limit:
            break
    return chains

_CAUSAL_VERB_PATTERN = (
    r"leads?\s+to|results?\s+in|causes?|drives?|induces?|triggers?|"
    r"promotes?|enhances?|increases?|activates?|maintains?|mediates?|enables?|"
    r"inhibits?|suppresses?|reduces?|decreases?|prevents?|attenuates?|"
    r"\u5bfc\u81f4|\u5f15\u8d77|\u4fc3\u8fdb|\u589e\u52a0|\u6fc0\u6d3b|\u7ef4\u6301|\u6291\u5236|\u964d\u4f4e|\u963b\u65ad"
)


def extract_causal_chains_heuristic(
    text: str,
    limit: int = 4,
    evidence_spans: list[dict[str, Any]] | None = None,
    source_url: str = "",
) -> list[dict[str, Any]]:
    clean = str(text or "").strip()
    if not clean:
        return []
    relation_pattern = re.compile(
        rf"(?P<source>[^.;:\n]{{2,220}}?)\s+(?P<verb>{_CAUSAL_VERB_PATTERN})\s+(?P<target>[^.;\n]{{2,240}})",
        flags=re.IGNORECASE,
    )
    inverse_pattern = re.compile(
        rf"(?P<target>[^.;:\n]{{2,220}}?)\s+(?:is|was|were|be)\s+(?P<verb>{_CAUSAL_VERB_PATTERN})\s+by\s+(?P<source>[^.;\n]{{2,240}})",
        flags=re.IGNORECASE,
    )
    chains: list[dict[str, Any]] = []
    for sentence in split_heuristic_sentences(clean):
        compact = " ".join(sentence.split())
        if len(compact) < 16 or causal_statement_is_negated(compact):
            continue
        match = inverse_pattern.search(compact) or relation_pattern.search(compact)
        if not match:
            continue
        trigger = clean_causal_endpoint(match.group("source"), role="source")
        outcome = clean_causal_endpoint(match.group("target"), role="target")
        if not trigger or not outcome or canonical_causal_entity(trigger) == canonical_causal_entity(outcome):
            continue
        relation, polarity = classify_causal_relation(str(match.group("verb") or ""))
        modality = causal_modality(compact)
        location = locate_causal_evidence(compact, evidence_spans, source_url)
        chains.append(
            {
                "chain_id": f"heuristic_{len(chains) + 1}",
                "trigger": trigger,
                "trigger_evidence": compact[:700],
                "trigger_location": location,
                "steps": [],
                "outcome": outcome,
                "outcome_evidence": compact[:700],
                "outcome_location": location,
                "relation": relation,
                "polarity": polarity,
                "modality": modality,
                "direct_relation": True,
                "causal_claim": modality == "asserted",
                "entities": [
                    {"text": trigger, "canonical": canonical_causal_entity(trigger), "role": "cause"},
                    {"text": outcome, "canonical": canonical_causal_entity(outcome), "role": "effect"},
                ],
                "observables": [],
                "interventions": [],
                "extraction_method": "explicit_causal_trigger_rule",
                "confidence": 0.76 if modality == "asserted" else 0.52,
            }
        )
        if len(chains) >= limit:
            break
    return chains


def extract_association_signals(
    text: str,
    limit: int = 6,
    evidence_spans: list[dict[str, Any]] | None = None,
    source_url: str = "",
) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?P<left>[^.;:\n]{2,220}?)\s+(?:is|was|were|are|be)?\s*"
        r"(?P<relation>associated with|correlated with|linked to|related to)\s+(?P<right>[^.;\n]{2,240})",
        flags=re.IGNORECASE,
    )
    signals: list[dict[str, Any]] = []
    for sentence in split_heuristic_sentences(text):
        compact = " ".join(sentence.split())
        match = pattern.search(compact)
        if not match:
            continue
        left = clean_causal_endpoint(match.group("left"), role="source")
        right = clean_causal_endpoint(match.group("right"), role="target")
        if not left or not right:
            continue
        signals.append(
            {
                "left": left,
                "right": right,
                "relation": "associated_with",
                "causal_claim": False,
                "modality": "non_causal_association",
                "evidence": compact[:700],
                "source_location": locate_causal_evidence(compact, evidence_spans, source_url),
                "extraction_method": "explicit_association_rule",
                "confidence": 0.72,
            }
        )
        if len(signals) >= limit:
            break
    return signals


def split_heuristic_sentences(text: str) -> list[str]:
    semantic_text = unwrap_prose_linebreaks(str(text or ""))
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+|\n{2,}", semantic_text)
        if sentence.strip()
    ]


def unwrap_prose_linebreaks(text: str) -> str:
    """Convert visual line wrapping into spaces while preserving structure."""

    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    pending = ""
    terminal = re.compile(r"[.!?\u3002\uff01\uff1f][\"'\u2019\u201d)\]]*$")
    structural = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|\|)")
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if pending:
                output.append(pending)
                pending = ""
            if output and output[-1] != "":
                output.append("")
            continue
        if not pending:
            pending = line
            continue
        if not terminal.search(pending) and not structural.match(pending) and not structural.match(line):
            pending = pending[:-1] + line if pending.endswith("-") and line[:1].islower() else pending + " " + line
        else:
            output.append(pending)
            pending = line
    if pending:
        output.append(pending)
    return "\n".join(output)


def clean_causal_endpoint(value: str, *, role: str) -> str:
    text = " ".join(str(value or "").split()).strip(" ,;:\u3002\uff0c\uff1a")
    text = re.sub(
        r"^(?:we|our (?:data|results)|this study|the study|the results|these findings)\s+"
        r"(?:show|shows|demonstrate|demonstrates|indicate|indicates|suggest|suggests|found|finds)\s+that\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if role == "source" and "," in text:
        text = text.rsplit(",", 1)[-1].strip()
    if role == "target":
        text = re.split(r"\s*(?:,|;|\bthereby\b|\bwhich\b|\bwhile\b|\bwhereas\b|\band thus\b)\s*", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    return text.strip(" ,;:\u3002\uff0c\uff1a")[:180]


def classify_causal_relation(verb: str) -> tuple[str, str]:
    normalized = str(verb or "").lower().strip()
    if any(token in normalized for token in ("inhibit", "suppress", "reduce", "decrease", "prevent", "attenuat", "\u6291\u5236", "\u964d\u4f4e", "\u963b\u65ad")):
        return "inhibits", "negative"
    if any(token in normalized for token in ("increase", "activate", "promote", "enhance", "maintain", "\u4fc3\u8fdb", "\u589e\u52a0", "\u6fc0\u6d3b", "\u7ef4\u6301")):
        return "promotes", "positive"
    if "mediate" in normalized:
        return "mediates", "positive"
    return "causes", "positive"


def causal_modality(sentence: str) -> str:
    lowered = str(sentence or "").lower()
    if re.search(r"\b(?:may|might|could|possibly|potentially|suggests?|appears? to|likely)\b", lowered):
        return "speculative"
    return "asserted"


def causal_statement_is_negated(sentence: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:does not|did not|do not|no evidence (?:that|for)|failed to)\s+(?:{_CAUSAL_VERB_PATTERN})\b",
            str(sentence or ""),
            flags=re.IGNORECASE,
        )
    )


def canonical_causal_entity(value: str) -> str:
    text = str(value or "").lower().replace("\u03b2", " beta ").replace("\u03b1", " alpha ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    key = " ".join(text.split())
    aliases = {
        "interleukin 2": "il2",
        "il 2": "il2",
        "interleukin 6": "il6",
        "il 6": "il6",
        "tumor necrosis factor alpha": "tnf alpha",
    }
    return aliases.get(key, key)


def locate_causal_evidence(
    evidence_text: str,
    evidence_spans: list[dict[str, Any]] | None,
    source_url: str,
) -> dict[str, Any]:
    try:
        from ._pdf_extraction import locate_evidence_span
    except ImportError:
        from _pdf_extraction import locate_evidence_span
    location = locate_evidence_span(evidence_text, evidence_spans)
    if not location and source_url:
        location = {"source_url": source_url}
    return location


def merge_paper_structures(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, list):
            if value:
                merged[key] = value
        elif str(value or "").strip():
                merged[key] = value
    return apply_paper_role_exclusivity(merged)


_EXPLICIT_LIMITATION_PATTERN = re.compile(
    r"\b(?:limitations?|limited\s+by|we\s+(?:did\s+not|could\s+not|were\s+unable)|"
    r"(?:remains?|remained)\s+(?:unknown|unclear|unresolved)|future\s+work|"
    r"does\s+not\s+address|cannot|unable\s+to|lack\s+of|small\s+sample|"
    r"boundary\s+condition|open\s+(?:problem|question)|further\s+(?:study|research)\s+is\s+(?:needed|required))\b",
    flags=re.IGNORECASE,
)
_SUPPORTED_CONTRIBUTION_PATTERN = re.compile(
    r"\b(?:we\s+(?:found|showed|demonstrated|observed|measured|identified|developed|introduced|propose|present|report)|"
    r"(?:results?|findings?)\s+(?:show|demonstrate|reveal|indicate)|"
    r"(?:showed|demonstrated|revealed|achieved|improved|outperformed|predicted|validated|established|enabled|reduced|increased))\b",
    flags=re.IGNORECASE,
)


def paper_role_text_key(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\[\s*(?:\.\.\.\s*)?truncated\s*\]", " ", text)
    text = re.sub(r"\.\.\.+$", " ", text.strip())
    return " ".join(re.findall(r"[a-z0-9\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff\u4e00-\u9fff]+", text))


def paper_role_texts_overlap(left: Any, right: Any) -> bool:
    """Detect exact, prefix-truncated, and near-verbatim cross-role copies."""

    left_key = paper_role_text_key(left)
    right_key = paper_role_text_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shorter, longer = sorted((left_key, right_key), key=len)
    if len(shorter) >= 80 and shorter in longer:
        return True
    left_tokens = left_key.split()
    right_tokens = right_key.split()
    if min(len(left_tokens), len(right_tokens)) < 12:
        return False
    left_set, right_set = set(left_tokens), set(right_tokens)
    return len(left_set & right_set) / max(1, len(left_set | right_set)) >= 0.9


def apply_paper_role_exclusivity(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure positive findings and limitations cannot reuse one passage.

    Extraction models occasionally copy an abstract prefix into every requested
    field.  This function preserves one scientifically appropriate role and
    removes its duplicates from the other scalar/list fields.  It deliberately
    does not invent a missing limitation.
    """

    normalized = dict(payload)
    contribution = " ".join(str(normalized.get("contribution") or "").split())
    limitation = " ".join(str(normalized.get("limitation") or "").split())
    strengths = unique_role_values(normalized.get("strengths"))
    improvements = unique_role_values(normalized.get("improvements") or normalized.get("limitations"))
    conflicts: list[dict[str, str]] = []

    abstract = str(normalized.get("abstract") or "")
    conclusion = str(normalized.get("conclusion") or "")
    if contribution_is_background_abstract_copy(contribution, abstract):
        replacement = select_supported_contribution(abstract, conclusion)
        if replacement and not paper_role_texts_overlap(replacement, contribution):
            conflicts.append(
                {
                    "removed": "contribution",
                    "kept": "supported_result_sentence",
                    "reason": "background_abstract_prefix_replaced",
                }
            )
            contribution = replacement
    filtered_strengths: list[str] = []
    for strength in strengths:
        if contribution_is_background_abstract_copy(strength, abstract):
            conflicts.append({"removed": "strengths", "kept": "abstract", "reason": "background_abstract_prefix"})
        else:
            filtered_strengths.append(strength)
    strengths = filtered_strengths
    filtered_improvements: list[str] = []
    for improvement in improvements:
        if contribution_is_background_abstract_copy(improvement, abstract):
            conflicts.append({"removed": "improvements", "kept": "abstract", "reason": "background_abstract_prefix"})
        else:
            filtered_improvements.append(improvement)
    improvements = filtered_improvements
    if contribution_is_background_abstract_copy(limitation, abstract) and not _EXPLICIT_LIMITATION_PATTERN.search(limitation):
        conflicts.append(
            {
                "removed": "limitation",
                "kept": "abstract",
                "reason": "background_abstract_prefix_without_explicit_limitation",
            }
        )
        limitation = ""

    if paper_role_texts_overlap(contribution, limitation):
        if _EXPLICIT_LIMITATION_PATTERN.search(limitation):
            conflicts.append({"removed": "contribution", "kept": "limitation", "reason": "cross_role_duplicate"})
            contribution = ""
        else:
            conflicts.append({"removed": "limitation", "kept": "contribution", "reason": "cross_role_duplicate_without_explicit_limitation"})
            limitation = ""

    # Scalar fields are the canonical summary for their role; parallel lists
    # should add information, not repeat that same text.
    strengths = remove_overlapping_role_values(strengths, [contribution], "strengths", "contribution", conflicts)
    improvements = remove_overlapping_role_values(improvements, [limitation], "improvements", "limitation", conflicts)

    retained_strengths: list[str] = []
    for strength in strengths:
        duplicate_improvements = [item for item in improvements if paper_role_texts_overlap(strength, item)]
        if duplicate_improvements and any(_EXPLICIT_LIMITATION_PATTERN.search(item) for item in duplicate_improvements):
            conflicts.append({"removed": "strengths", "kept": "improvements", "reason": "cross_role_duplicate"})
            continue
        retained_strengths.append(strength)
        if duplicate_improvements:
            improvements = [item for item in improvements if item not in duplicate_improvements]
            conflicts.append({"removed": "improvements", "kept": "strengths", "reason": "cross_role_duplicate_without_explicit_limitation"})
    strengths = retained_strengths

    improvements = remove_overlapping_role_values(improvements, [contribution] + strengths, "improvements", "positive_finding", conflicts)
    if limitation and any(paper_role_texts_overlap(limitation, item) for item in [contribution] + strengths):
        if _EXPLICIT_LIMITATION_PATTERN.search(limitation):
            contribution = "" if paper_role_texts_overlap(limitation, contribution) else contribution
            strengths = [item for item in strengths if not paper_role_texts_overlap(limitation, item)]
        else:
            limitation = ""

    normalized["contribution"] = contribution
    normalized["limitation"] = limitation
    normalized["strengths"] = strengths
    normalized["improvements"] = improvements
    prior_conflicts = normalized.get("role_conflicts_resolved")
    normalized["role_conflicts_resolved"] = (
        list(prior_conflicts) if isinstance(prior_conflicts, list) else []
    ) + conflicts
    return normalized


def contribution_is_background_abstract_copy(contribution: str, abstract: str) -> bool:
    contribution_key = paper_role_text_key(contribution)
    abstract_key = paper_role_text_key(abstract)
    abstract_key = re.sub(r"^(?:abstract|summary)\s+", "", abstract_key)
    if len(contribution_key) < 80 or not abstract_key.startswith(contribution_key):
        return False
    return _SUPPORTED_CONTRIBUTION_PATTERN.search(contribution) is None


def select_supported_contribution(abstract: str, conclusion: str) -> str:
    """Select a result-bearing sentence when a model copied abstract background."""

    candidates: list[tuple[int, int, str]] = []
    combined = "\n\n".join(value for value in (conclusion, abstract) if value)
    for index, sentence in enumerate(split_heuristic_sentences(combined)):
        clean = " ".join(sentence.split()).strip()
        if len(clean) < 45 or _EXPLICIT_LIMITATION_PATTERN.search(clean):
            continue
        cue_count = len(_SUPPORTED_CONTRIBUTION_PATTERN.findall(clean))
        if cue_count == 0:
            continue
        numeric_bonus = 2 if re.search(r"\b\d+(?:\.\d+)?%?\b", clean) else 0
        specificity_bonus = 1 if len(clean.split()) >= 12 else 0
        candidates.append((cue_count * 5 + numeric_bonus + specificity_bonus, index, clean))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2][:700]


def unique_role_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else ([value] if value else [])
    selected: list[str] = []
    for item in values:
        clean = " ".join(str(item or "").split()).strip()
        if clean and not any(paper_role_texts_overlap(clean, current) for current in selected):
            selected.append(clean)
    return selected


def remove_overlapping_role_values(
    values: list[str],
    references: list[str],
    removed_role: str,
    kept_role: str,
    conflicts: list[dict[str, str]],
) -> list[str]:
    retained: list[str] = []
    for value in values:
        if any(reference and paper_role_texts_overlap(value, reference) for reference in references):
            conflicts.append({"removed": removed_role, "kept": kept_role, "reason": "same_role_summary_duplicate"})
        else:
            retained.append(value)
    return retained

def extraction_quality_report(record: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import is_unknown_value, normalize_label, normalize_space, unique_preserve_order
    except ImportError:
        from _utils import is_unknown_value, normalize_label, normalize_space, unique_preserve_order
    fields = {
        "method": normalize_label(record.get("method", "")),
        "scenario": normalize_label(record.get("scenario", "")),
        "benchmark": normalize_label(record.get("benchmark", "")),
    }
    unknown_fields = [name for name, value in fields.items() if is_unknown_value(value)]
    abstract = normalize_space(str(record.get("abstract") or ""))
    conclusion = normalize_space(str(record.get("conclusion") or ""))
    text = normalize_space(
        " ".join(
            str(record.get(key, ""))
            for key in ("title", "abstract", "conclusion", "full_text_excerpt", "contribution", "limitation")
            if record.get(key)
        )
    )
    flags: list[str] = []
    if invalid_placeholder_abstract(abstract):
        flags.append("invalid_placeholder_abstract")
    if not abstract or invalid_placeholder_abstract(abstract):
        flags.append("missing_abstract")
    elif len(abstract) < 220:
        flags.append("short_abstract")
    if looks_truncated(abstract):
        flags.append("truncated_abstract")
    if not conclusion:
        flags.append("missing_conclusion")
    if unknown_fields:
        flags.append("unknown_fields")
    if len(unknown_fields) >= 2:
        flags.append("unknown_fields_high")
    if fields["benchmark"] in {"unknown benchmark", "unspecified benchmark", "unknown"}:
        flags.append("missing_benchmark")
    if text and background_only_text(text):
        flags.append("background_only_text")
    unknown_ratio = round(len(unknown_fields) / max(1, len(fields)), 3)
    score = 1.0
    score -= 0.24 * len(unknown_fields)
    if "missing_abstract" in flags:
        score -= 0.25
    elif "short_abstract" in flags:
        score -= 0.12
    if "truncated_abstract" in flags:
        score -= 0.2
    if "background_only_text" in flags:
        score -= 0.12
    score = round(max(0.0, min(1.0, score)), 3)
    return {
        "score": score,
        "unknown_ratio": unknown_ratio,
        "unknown_fields": unknown_fields,
        "abstract_chars": len(abstract),
        "flags": unique_preserve_order(flags),
        "needs_enrichment": (
            "missing_abstract" in flags
            or "invalid_placeholder_abstract" in flags
            or "truncated_abstract" in flags
            or ("short_abstract" in flags and len(unknown_fields) >= 1)
        ),
        "needs_llm_retry": len(unknown_fields) >= 1 or "background_only_text" in flags,
        "requires_human_review": score < 0.55 or len(unknown_fields) >= 2,
    }

def invalid_placeholder_abstract(text: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    clean = normalize_space(text)
    if not clean:
        return True
    lowered = clean.lower().strip(" :;.-")
    if lowered in {"abstract", "summary", "conclusion", "conclusions", "result", "results", "not available", "no abstract available"}:
        return True
    if re.fullmatch(r"(abstract|summary|conclusion|conclusions|results?)\s*:?", clean, flags=re.IGNORECASE):
        return True
    return len(clean.split()) <= 2 and any(label in lowered for label in ("abstract", "summary", "conclusion", "result"))

def looks_truncated(text: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    stripped = normalize_space(text)
    if not stripped:
        return False
    lowered = stripped.lower().rstrip()
    if lowered.endswith("..."):
        return True
    return bool(re.search(r"\b(using|via|through|based on|with|by|as|an|a|the)\s*(?:\.\.\.)?$", lowered))

def background_only_text(text: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    lowered = normalize_space(text).lower()
    if not lowered:
        return False
    background_markers = [
        "is an effective approach",
        "is important",
        "has attracted",
        "developing cost-effective",
        "urgent need",
        "major challenge",
        "promising strategy",
        "broad interest",
        "critical problem",
    ]
    evidence_markers = [
        "accuracy",
        "assessed",
        "baseline",
        "benchmark",
        "characterized",
        "compared",
        "demonstrates",
        "evaluated",
        "experiment",
        "measured",
        "metric",
        "model",
        "performance",
        "prediction",
        "protocol",
        "readout",
        "response",
        "score",
        "stability",
        "validated",
        "results",
    ]
    return any(marker in lowered for marker in background_markers) and not any(marker in lowered for marker in evidence_markers)

def maybe_llm_reextract_structure(payload: dict[str, Any], *, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    quality = extraction_quality_report(payload)
    if not force and not quality.get("needs_llm_retry"):
        return payload, {"attempted": False, "succeeded": False, "error": ""}
    labeled_fields = [
        ("Title", payload.get("title", "")),
        ("Venue", payload.get("venue", "")),
        ("Year", payload.get("year", "")),
        ("Citation", payload.get("citation", "")),
        ("Abstract", payload.get("abstract", "")),
        ("Conclusion", payload.get("conclusion", "")),
        ("Full text excerpt", payload.get("full_text_excerpt", "")),
    ]
    text = "\n\n".join(
        f"{label}: {value}"
        for label, value in labeled_fields
        if normalize_space(str(value or ""))
    )
    try:
        parsed = extract_paper_structure(text, use_llm=True)
    except Exception as exc:
        return payload, {"attempted": True, "succeeded": False, "error": str(exc)}
    merged = merge_paper_structures(payload, parsed)
    extractor = str(parsed.get("extractor") or "")
    status = str(parsed.get("status") or "")
    error = str(parsed.get("llm_error") or "")
    return merged, {
        "attempted": True,
        "succeeded": status == "STRUCTURED_BY_LLM" and not error,
        "error": error,
        "extractor": extractor,
        "status": status,
    }


def resume_pending_fulltext_structuring(
    project: dict[str, Any],
    *,
    max_records: int | None = None,
) -> dict[str, Any]:
    """Retry canonical pending documents once without redownloading PDFs.

    This is intentionally project-central rather than tied to a new SH
    binding: the same cached Markdown is structured at most once, then every
    already-audited binding can reuse the completed canonical record.
    """

    records = [
        item for item in (project.get("papergraph") or []) if isinstance(item, dict)
    ]
    attempted = 0
    completed = 0
    failed = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    structured_fields = (
        "abstract",
        "conclusion",
        "strengths",
        "improvements",
        "method",
        "scenario",
        "benchmark",
        "contribution",
        "limitation",
    )
    for record in records:
        if max_records is not None and attempted >= max(0, int(max_records)):
            break
        state = (
            record.get("fulltext_structuring")
            if isinstance(record.get("fulltext_structuring"), dict)
            else {}
        )
        if str(state.get("status") or "").lower() != "metadata_plus_fulltext_pending_structuring":
            continue
        if not assess_full_text_acquisition(record).get("full_text_available"):
            skipped += 1
            continue
        payload = {
            key: deepcopy(record.get(key))
            for key in (
                "title",
                "venue",
                "year",
                "citation",
                "abstract",
                "conclusion",
                "full_text_excerpt",
                "strengths",
                "improvements",
                "method",
                "scenario",
                "benchmark",
                "contribution",
                "limitation",
            )
        }
        attempted += 1
        parsed, retry = maybe_llm_reextract_structure(payload, force=True)
        if retry.get("succeeded"):
            for field_name in structured_fields:
                if field_name in parsed and parsed.get(field_name) not in (None, "", [], {}):
                    record[field_name] = deepcopy(parsed[field_name])
            completed_state = _fulltext_structuring_state(
                eligibility={
                    "eligible": True,
                    "role": str(state.get("role") or "pending_retry"),
                    "reason": "pending_canonical_fulltext_retry",
                },
                use_llm=True,
                llm_retry=retry,
                deterministic_complete=False,
            )
            record["fulltext_structuring"] = completed_state
            extraction_quality = extraction_quality_report(record)
            extraction_quality["llm_retry"] = dict(retry)
            extraction_quality["fulltext_structuring"] = dict(completed_state)
            record["extraction_quality"] = extraction_quality
            acquisition = (
                dict(record.get("full_text_acquisition") or {})
                if isinstance(record.get("full_text_acquisition"), dict)
                else {}
            )
            acquisition.update(
                {
                    "status": "AVAILABLE",
                    "available": True,
                    "excerpt_chars": len(str(record.get("full_text_excerpt") or "")),
                    "target_policy": "subhypothesis_full_text_required_for_direct_evidence_v1",
                    "structuring_status": completed_state["status"],
                    "eligible_for_evidence_admission": True,
                }
            )
            record["full_text_acquisition"] = acquisition
            record.pop("fulltext_pending_structuring", None)
            record["updatedAt"] = time.time()
            paper_id = str(record.get("paper_id") or "")
            for evidence in project.get("evidence") or []:
                if not isinstance(evidence, dict) or str(evidence.get("paper_id") or "") != paper_id:
                    continue
                evidence["fulltext_structuring"] = dict(completed_state)
                evidence["full_text_acquisition"] = dict(acquisition)
                evidence.pop("fulltext_pending_structuring", None)
            completed += 1
            continue
        failed += 1
        record["fulltext_structuring"] = {
            **state,
            "llm_attempted": bool(retry.get("attempted")),
            "llm_error": str(retry.get("error") or ""),
            "last_retry_at": time.time(),
        }
        failures.append(
            {
                "paper_id": str(record.get("paper_id") or ""),
                "error": str(retry.get("error") or "")[:300],
            }
        )
    if completed or failed:
        project["updatedAt"] = time.time()
    return {
        "schema_version": "pending_fulltext_structuring_resume_v1",
        "attempted": attempted,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "failures": failures,
    }

def is_low_information_field(value: str, field: str) -> bool:
    try:
        from ._models import GENERAL_BENCHMARK_CUES, GENERAL_METHOD_CUES, GENERAL_SCENARIO_CUES
        from ._utils import normalize_space
    except ImportError:
        from _models import GENERAL_BENCHMARK_CUES, GENERAL_METHOD_CUES, GENERAL_SCENARIO_CUES
        from _utils import normalize_space
    lowered = normalize_space(value).lower()
    if not lowered:
        return True
    generic_fragments = [
        "is an effective approach",
        "is important",
        "developing cost-effective",
        "has attracted",
        "urgent need",
        "background",
        "this study",
        "this paper",
        "research topic",
        "broad application",
        "significant challenge",
    ]
    if any(fragment in lowered for fragment in generic_fragments):
        return True
    if field in {"method", "benchmark"} and len(lowered) > 90:
        return True
    if field == "method" and not contains_any(lowered, GENERAL_METHOD_CUES):
        return len(lowered) > 80
    if field == "scenario" and not contains_any(lowered, GENERAL_SCENARIO_CUES):
        return len(lowered) > 100
    if field == "benchmark":
        if lowered in {"benchmark dataset", "benchmark data", "benchmark"}:
            return True
        if not contains_any(lowered, GENERAL_BENCHMARK_CUES):
            return len(lowered) > 80
    return False

def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)

def infer_ontology_field(text: str, field: str) -> str:
    try:
        from ._models import BENCHMARK_ONTOLOGY, METHOD_ONTOLOGY, SCENARIO_ONTOLOGY
        from ._utils import normalize_space, science_term_in_text
    except ImportError:
        from _models import BENCHMARK_ONTOLOGY, METHOD_ONTOLOGY, SCENARIO_ONTOLOGY
        from _utils import normalize_space, science_term_in_text
    lowered = normalize_space(text).lower()
    ontology = {
        "method": METHOD_ONTOLOGY,
        "scenario": SCENARIO_ONTOLOGY,
        "benchmark": BENCHMARK_ONTOLOGY,
    }.get(field, {})
    best_label = ""
    best_score = 0.0
    for label, patterns in ontology.items():
        if field == "benchmark" and not benchmark_allowed_for_context(label, lowered):
            continue
        score = sum(1.0 + min(len(pattern), 40) / 100.0 for pattern in patterns if science_term_in_text(pattern, lowered))
        if score > best_score:
            best_label = label
            best_score = score
    return best_label

def benchmark_allowed_for_context(label: str, lowered_text: str) -> bool:
    try:
        from ._models import FIELD_SPECIFIC_BENCHMARKS
    except ImportError:
        from _models import FIELD_SPECIFIC_BENCHMARKS
    required = FIELD_SPECIFIC_BENCHMARKS.get(label)
    if not required:
        return True
    return any(term in lowered_text for term in required)

def infer_generic_science_phrase(text: str, field: str) -> str:
    try:
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _utils import normalize_space, trim_text
    clean = normalize_space(text)
    if not clean:
        return ""
    patterns = {
        "method": [
            r"\b([A-Za-z][A-Za-z0-9 -]{2,60}\s(?:analysis|model|modeling|simulation|algorithm|assay|index|inversion|sequencing|spectroscopy|microscopy|trial|experiment|synthesis|characterization|optimization|inference|regression|classification))\b",
            r"\b(?:using|via|with|based on|by applying)\s+([A-Za-z][A-Za-z0-9 -]{2,60})\b",
        ],
        "scenario": [
            r"\b([A-Za-z][A-Za-z0-9 -]{2,70}\s(?:application|case|cohort|condition|dataset|diagnosis|discovery|domain|environment|experiment|forecasting|material|phenomenon|platform|population|prediction|process|sample|screening|setting|system|task|therapy))\b",
            r"\b(?:in|for|under|within|across)\s+([A-Za-z][A-Za-z0-9 -]{2,70}\s(?:application|case|classification|cohort|conditions|context|dataset|diagnosis|discovery|domain|environment|forecasting|population|prediction|regime|sample|scenario|screening|setting|system|task|therapy))\b",
        ],
        "benchmark": [
            r"\b([A-Za-z][A-Za-z0-9 -]{2,60}\s(?:accuracy|baseline|criterion|efficiency|endpoint|error|index|metric|observable|performance|readout|response|score|stability|uncertainty|validation|yield))\b",
            r"\b(?:assessed by|benchmarked by|evaluated by|measured by|measures|reported by|reports|validated by|using)\s+([A-Za-z][A-Za-z0-9 -]{2,60})\b",
        ],
    }.get(field, [])
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = normalize_space(match.group(1)).strip(" .,:;")
        phrase = clean_extracted_science_phrase(phrase, field)
        phrase = trim_text(phrase, 90)
        if phrase and not is_generic_phrase(phrase):
            return phrase.lower()
    return ""

def clean_extracted_science_phrase(phrase: str, field: str) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    cleaned = normalize_space(phrase)
    if field == "benchmark":
        for marker in (
            " and measures ",
            " and measured ",
            " and reports ",
            " and reported ",
            " and evaluates ",
            " and evaluated ",
            " with ",
        ):
            if marker in cleaned.lower():
                parts = re.split(re.escape(marker), cleaned, maxsplit=1, flags=re.IGNORECASE)
                cleaned = parts[-1]
                break
    if field == "scenario":
        cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
    return normalize_space(cleaned).strip(" .,:;")

def is_generic_phrase(phrase: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    lowered = normalize_space(phrase).lower()
    generic = {
        "this study",
        "the paper",
        "our results",
        "an effective approach",
        "a new method",
        "the proposed method",
        "current study",
    }
    if lowered in generic:
        return True
    return len(lowered.split()) > 9

def record_source_text(record: dict[str, Any]) -> str:
    return "\n".join(
        str(record.get(key, ""))
        for key in (
            "title",
            "citation",
            "abstract",
            "conclusion",
            "full_text_excerpt",
        )
        if record.get(key)
    )

_METHOD_MARKERS = (
    "randomized", "randomised", "clinical trial", "cohort", "case-control", "single-cell",
    "rna-seq", "sequencing", "microscopy", "spectroscopy", "assay", "regression",
    "cox proportional", "mixed-effects", "simulation", "mouse model", "in vivo", "in vitro",
    "meta-analysis", "systematic review", "flow cytometry", "western blot", "crisper",
)
_SCENARIO_MARKERS = (
    "patient", "participant", "cohort", "mouse", "mice", "murine", "human", "cell line",
    "organoid", "tissue", "plasma", "serum", "population", "dataset", "in vivo", "in vitro",
)
_BENCHMARK_MARKERS = (
    "primary endpoint", "endpoint", "hazard ratio", "confidence interval", "accuracy", "auc",
    "survival", "toxicity", "response rate", "effect size", "p value", "p-value", "validation",
    "sensitivity", "specificity", "dose-response", "readout", "yield", "purity", "potency",
)


def extract_methodology_evidence(
    text: str,
    evidence_spans: list[dict[str, Any]] | None = None,
    source_url: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    sections = split_structured_sections(text)
    evidence: list[dict[str, Any]] = []
    methods: list[str] = []
    scenarios: list[str] = []
    benchmarks: list[str] = []
    populations: list[str] = []
    outcomes: list[str] = []
    for section, section_text in sections:
        section_lower = section.lower()
        is_method_section = any(token in section_lower for token in ("method", "material", "experimental", "study design", "statistical"))
        for sentence in split_heuristic_sentences(section_text):
            compact = " ".join(sentence.split())
            if len(compact) < 18:
                continue
            lowered = compact.lower()
            location = locate_causal_evidence(compact, evidence_spans, source_url)
            if is_method_section or any(marker in lowered for marker in _METHOD_MARKERS):
                method_terms = matched_method_terms(compact)
                if method_terms:
                    methods.extend(method_terms)
                    evidence.append(methodology_evidence_item("method", compact, section, location))
            if any(marker in lowered for marker in _SCENARIO_MARKERS):
                population = extract_population_phrase(compact)
                if population:
                    populations.append(population)
                    scenarios.append(population)
                    evidence.append(methodology_evidence_item("population", compact, section, location))
            if any(marker in lowered for marker in _BENCHMARK_MARKERS):
                benchmark_terms = matched_benchmark_terms(compact)
                if benchmark_terms:
                    benchmarks.extend(benchmark_terms)
                    outcomes.extend(benchmark_terms)
                    evidence.append(methodology_evidence_item("outcome", compact, section, location))
            if len(evidence) >= limit:
                break
        if len(evidence) >= limit:
            break
    return {
        "method": "; ".join(unique_text_values(methods, 3)),
        "scenario": "; ".join(unique_text_values(scenarios, 2)),
        "benchmark": "; ".join(unique_text_values(benchmarks, 3)),
        "population": unique_text_values(populations, 3),
        "outcome": unique_text_values(outcomes, 4),
        "evidence": evidence[:limit],
        "extractor": "section_dictionary_pattern",
    }


def split_structured_sections(text: str) -> list[tuple[str, str]]:
    raw = str(text or "")
    matches = list(
        re.finditer(
            r"\[SECTION:\s*(?P<heading>[^|\]]+?)(?:\s*\|\s*pages?[^\]]*)?\]\s*(?P<body>.*?)(?=\n\s*\[SECTION:|\n\s*\[(?:KEYWORD|TABLES|FIGURE)|\Z)",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    if matches:
        return [(match.group("heading").strip(), match.group("body").strip()) for match in matches if match.group("body").strip()]
    return [("Document body", raw)] if raw.strip() else []


def matched_method_terms(sentence: str) -> list[str]:
    lowered = sentence.lower()
    canonical = [
        ("single-cell rna-seq", ("single-cell rna-seq", "single cell rna-seq", "single-cell sequencing")),
        ("cox proportional hazards", ("cox proportional", "cox regression")),
        ("randomized trial", ("randomized", "randomised")),
        ("mouse model", ("mouse model", "mice", "murine")),
    ]
    matches = [label for label, terms in canonical if any(term in lowered for term in terms)]
    for marker in _METHOD_MARKERS:
        if marker in lowered and marker not in matches:
            matches.append(marker)
    return unique_text_values(matches, 4)


def matched_benchmark_terms(sentence: str) -> list[str]:
    lowered = sentence.lower()
    matches = [marker for marker in _BENCHMARK_MARKERS if marker in lowered]
    return unique_text_values(matches, 4)


def extract_population_phrase(sentence: str) -> str:
    match = re.search(
        r"\b(?:n\s*=\s*\d+\s+)?(?:\d+\s+)?(?:patients?|participants?|subjects?|mice|mouse|murine\s+models?|human\s+cohorts?|cell\s+lines?|organoids?|populations?)\b[^,;.]{0,100}",
        sentence,
        flags=re.IGNORECASE,
    )
    if match:
        return " ".join(match.group(0).split()).strip(" ,;:")
    return ""


def methodology_evidence_item(field: str, text: str, section: str, location: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": field,
        "text": text[:500],
        "section": section,
        "source_location": location,
        "evidence_level": "explicit_text",
        "confidence": 0.82 if section.lower().startswith(("method", "material", "experimental", "study design", "statistical")) else 0.68,
    }


def unique_text_values(values: list[str], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").split()).strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        selected.append(clean)
        if len(selected) >= limit:
            break
    return selected


def prefer_structured_field(current: str, suggested: str, field: str) -> str:
    if not suggested:
        return current
    if not current or is_low_information_field(current, field):
        return suggested
    return current


def parse_paper_text(text: str) -> dict[str, Any]:
    try:
        from ._gap_detection import extract_gap_signals_from_text
        from ._utils import extract_section, extract_year, first_nonempty, first_sentences, last_sentences, normalize_space, repair_unknown_field
    except ImportError:
        from _gap_detection import extract_gap_signals_from_text
        from _utils import extract_section, extract_year, first_nonempty, first_sentences, last_sentences, normalize_space, repair_unknown_field
    clean = normalize_space(text)
    title = extract_labeled_value(clean, ["title"])
    doi = extract_doi(clean)
    arxiv_id = extract_labeled_value(clean, ["arxiv", "arxiv id", "arxiv_id"])
    authors = extract_authors(clean)
    year = extract_year(clean)
    venue = extract_labeled_value(clean, ["venue", "journal", "conference"])
    abstract = extract_section(clean, ["abstract", "summary"]) or first_sentences(clean, 3)
    conclusion = extract_section(clean, ["conclusion", "conclusions", "discussion"]) or last_sentences(clean, 3)
    strengths = extract_bullets_or_sentences(clean, ["advantage", "strength", "contribution", "novel", "improve"], limit=5)
    improvements = extract_bullets_or_sentences(clean, ["limitation", "future work", "weakness", "challenge", "remain"], limit=5)
    gap_signals = extract_gap_signals_from_text(clean, citation="", limit=12)
    method = infer_field(clean, ["method", "approach", "model", "framework"], default="")
    scenario = infer_field(clean, ["scenario", "application", "domain", "task"], default="")
    benchmark = infer_field(clean, ["benchmark", "dataset", "data set", "corpus"], default="")
    methodology = extract_methodology_evidence(clean)
    method = prefer_structured_field(method, str(methodology.get("method") or ""), "method")
    scenario = prefer_structured_field(scenario, str(methodology.get("scenario") or ""), "scenario")
    benchmark = prefer_structured_field(benchmark, str(methodology.get("benchmark") or ""), "benchmark")
    method = repair_unknown_field(method, clean, "method")
    scenario = repair_unknown_field(scenario, clean, "scenario")
    benchmark = repair_unknown_field(benchmark, clean, "benchmark")
    contribution = first_nonempty(strengths) or first_sentences(clean, 1)
    limitation = (
        str(gap_signals[0].get("text", ""))
        if gap_signals
        else first_nonempty(improvements) or "No explicit limitation extracted."
    )
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id=arxiv_id) if title or doi or arxiv_id else ""
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "abstract": abstract,
        "conclusion": conclusion,
        "strengths": strengths,
        "improvements": improvements,
        "method": method,
        "scenario": scenario,
        "benchmark": benchmark,
        "contribution": contribution,
        "limitation": limitation,
        "gap_signals": gap_signals,
        "causal_chains": extract_causal_chains_heuristic(clean),
        "structured_methodology": methodology,
    }

def extract_labeled_value(text: str, labels: list[str]) -> str:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    for label in labels:
        pattern = re.compile(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$")
        match = pattern.search(text)
        if match:
            return trim_text(match.group(1), 300)
    return ""

def extract_doi(text: str) -> str:
    labeled = extract_labeled_value(text, ["doi"])
    if labeled:
        return normalize_doi(labeled)
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", text)
    return normalize_doi(match.group(0)) if match else ""

def normalize_doi(value: str) -> str:
    cleaned = str(value or "").strip().rstrip(".,;)")
    cleaned = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", cleaned)
    return cleaned

def extract_authors(text: str) -> list[str]:
    raw = extract_labeled_value(text, ["authors", "author"])
    if not raw:
        return []
    pieces = re.split(r"\s*(?:;|,|\band\b|&)\s*", raw)
    return [piece.strip() for piece in pieces if piece.strip()][:20]

def build_citation(
    *,
    title: str,
    authors: list[str],
    year: str,
    doi: str,
    arxiv_id: str,
) -> str:
    parts: list[str] = []
    if authors:
        first_author = authors[0]
        parts.append(f"{first_author} et al." if len(authors) > 1 else first_author)
    if year:
        parts.append(f"({year})")
    if title:
        parts.append(title)
    if doi:
        parts.append(f"doi:{doi}")
    elif arxiv_id:
        parts.append(f"arXiv:{arxiv_id}")
    return " ".join(parts).strip() or title or doi or arxiv_id or "uncited paper"

def extract_bullets_or_sentences(text: str, keywords: list[str], limit: int = 5) -> list[str]:
    try:
        from ._utils import split_sentences, trim_text, unique_preserve_order
    except ImportError:
        from _utils import split_sentences, trim_text, unique_preserve_order
    candidates: list[str] = []
    for line in text.splitlines():
        if not re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line):
            continue
        stripped = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(keyword in lowered for keyword in keywords):
            candidates.append(trim_text(stripped, 300))
    sentences = split_sentences(unwrap_prose_linebreaks(text))
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            candidates.append(trim_text(sentence, 300))
    return unique_preserve_order(candidates)[:limit]

def infer_field(text: str, keywords: list[str], default: str) -> str:
    try:
        from ._utils import split_sentences, trim_text
    except ImportError:
        from _utils import split_sentences, trim_text
    for sentence in split_sentences(text):
        lowered = sentence.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        if len(sentence) <= 220:
            return trim_text(sentence, 220)
    return default

def score_evidence_credibility(
    *,
    title: str,
    citation: str,
    provider: str,
    doi: str,
    arxiv_id: str,
    semantic_scholar_id: str,
    url: str,
    abstract: str,
    conclusion: str,
    venue: str,
    year: str,
) -> tuple[float, list[str]]:
    try:
        from ._literature_scoring import is_reputable_venue, publication_quality_assessment
        from ._models import LITERATURE_PROVIDERS
    except ImportError:
        from _literature_scoring import is_reputable_venue, publication_quality_assessment
        from _models import LITERATURE_PROVIDERS
    score = 0.2
    reasons: list[str] = ["base record"]
    if title and citation:
        score += 0.15
        reasons.append("has title and citation")
    if doi:
        score += 0.2
        reasons.append("has DOI")
    if arxiv_id or semantic_scholar_id:
        score += 0.15
        reasons.append("has scholarly identifier")
    if url:
        score += 0.05
        reasons.append("has URL")
    if len(abstract) > 200:
        score += 0.1
        reasons.append("has substantial abstract")
    if len(conclusion) > 100:
        score += 0.05
        reasons.append("has conclusion/discussion")
    if provider in LITERATURE_PROVIDERS or provider.startswith("manual"):
        score += 0.05
        reasons.append("provider recorded")
    if is_reputable_venue(venue.lower()) or any(marker in venue.lower() for marker in ("neurips", "icml", "iclr", "npj")):
        score += 0.1
        reasons.append("high-prestige venue marker")
    quality = publication_quality_assessment(
        {
            "venue": venue,
            "provider": provider,
            "url": url,
            "doi": doi,
            "year": year,
        }
    )
    if quality["venue_quality"] == "suspicious":
        score -= 0.25
        reasons.append("suspicious venue/publisher")
    elif quality["venue_quality"] == "reputable":
        score += 0.08
        reasons.append("reputable venue")
    elif quality["venue_quality"] == "preprint":
        score -= 0.03
        reasons.append("preprint venue")
    if quality["quality_score"] < 0.55:
        score -= 0.08
        reasons.append("requires human quality review")
    if quality["venue_quality"] == "suspicious":
        score *= 0.45
        reasons.append("credibility multiplied down by suspicious publication venue")
    elif quality["quality_score"] < 0.55:
        score *= 0.65
        reasons.append("credibility multiplied down by low publication quality")
    if re.fullmatch(r"\d{4}", str(year)):
        score += 0.05
        reasons.append("has publication year")
    return round(max(0.05, min(score, 1.0)), 2), reasons

def paper_unique_key(
    *,
    title: str,
    citation: str,
    doi: str,
    arxiv_id: str,
    semantic_scholar_id: str,
    url: str,
    openalex_id: str = "",
    pmid: str = "",
) -> str:
    doi = normalize_optional_identifier(doi)
    openalex_id = normalize_optional_identifier(openalex_id)
    arxiv_id = normalize_optional_identifier(arxiv_id)
    semantic_scholar_id = normalize_optional_identifier(semantic_scholar_id)
    pmid = normalize_optional_identifier(pmid)
    url = normalize_optional_identifier(url)
    if doi:
        return "doi:" + normalize_identifier(doi)
    if openalex_id:
        return "openalex:" + normalize_identifier(openalex_id)
    if arxiv_id:
        return "arxiv:" + normalize_identifier(arxiv_id)
    if semantic_scholar_id:
        return "s2:" + normalize_identifier(semantic_scholar_id)
    if pmid:
        return "pmid:" + normalize_identifier(pmid)
    if url:
        return "url:" + normalize_identifier(url)
    return "text:" + normalize_identifier(title or citation)

def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_") or "unknown"

