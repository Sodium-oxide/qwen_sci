"""Bounded persistence for legacy monolithic science-project JSON.

Extraction and alignment code may use rich transient reports while processing
one paper.  A project snapshot should retain one canonical scientific record,
not every copy made for intermediate quality checks or compatibility views.
The functions here are deliberately pure and idempotent so both legacy JSON
and normalized per-paper storage can apply the same policy before writing.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any
import json

try:
    from ._evidence_storage import assertion_source_span_ids, compact_record_v2_evidence
except ImportError:
    from _evidence_storage import assertion_source_span_ids, compact_record_v2_evidence


PROJECT_STORAGE_COMPACTION_SCHEMA_VERSION = "science_project_storage_compaction_v1"
TABLE_CANDIDATE_AUDIT_SCHEMA_VERSION = "markdown_table_candidate_audit_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _same_json(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def extraction_report_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded quality summary without copying extracted content."""

    source = report if isinstance(report, dict) else {}
    non_text = source.get("non_text") if isinstance(source.get("non_text"), dict) else {}
    validation = source.get("validation") if isinstance(source.get("validation"), dict) else {}
    admission = (
        source.get("evidence_admission")
        if isinstance(source.get("evidence_admission"), dict)
        else {}
    )
    return {
        "schema_version": "full_text_extraction_quality_summary_v1",
        "status": str(source.get("status") or ""),
        "backend": str(source.get("backend") or ""),
        "source_representation": str(source.get("source_representation") or ""),
        "full_text_chars": int(source.get("full_text_chars") or 0),
        "excerpt_chars": int(source.get("excerpt_chars") or 0),
        "evidence_span_count": len(source.get("evidence_spans") or []),
        "table_evidence_count": len(non_text.get("table_evidence") or []),
        "caption_evidence_count": len(non_text.get("caption_evidence") or []),
        "validation_passed": bool(
            validation.get("passes")
            or validation.get("valid")
            or validation.get("accepted")
        ),
        "needs_supplement": bool(validation.get("needs_supplement")),
        "allows_direct_evidence": bool(admission.get("allows_direct_evidence")),
        "requires_human_review": bool(admission.get("requires_human_review")),
        "canonical_report": "papergraph.full_text_enrichment",
        "content_omitted": True,
    }


def _bounded_rejected_table_audit(
    rejected_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    sampled_reasons: set[str] = set()
    for raw in rejected_candidates:
        if not isinstance(raw, dict):
            continue
        reason = str(raw.get("reason") or "unspecified")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason in sampled_reasons or len(samples) >= 5:
            continue
        sampled_reasons.add(reason)
        rendered = {
            "sha256": str(raw.get("sha256") or ""),
            "source_locator": str(raw.get("source_locator") or ""),
            "heading": str(raw.get("heading") or ""),
            "reason": reason,
            "columns": int(raw.get("columns") or 0),
            "rows": int(raw.get("rows") or 0),
        }
        # Old records lack a line locator.  The hash still makes the audit
        # sample stable without retaining the rejected fragment itself.
        samples.append({key: value for key, value in rendered.items() if value not in {"", 0}})
    count = sum(reason_counts.values())
    return {
        "count": count,
        "reason_counts": dict(sorted(reason_counts.items())),
        "samples": samples,
        "samples_truncated": count > len(samples),
    }


def compact_non_text_audit(non_text: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, int]]:
    """Remove rejected fragments and redundant accepted-table manifests."""

    compacted = dict(non_text or {})
    removed_rejected = compacted.pop("rejected_table_candidates", [])
    removed_manifest = compacted.pop("table_manifest", [])
    if not isinstance(removed_rejected, list):
        removed_rejected = []
    if not isinstance(removed_manifest, list):
        removed_manifest = []

    audit = (
        dict(compacted.get("table_candidate_audit") or {})
        if isinstance(compacted.get("table_candidate_audit"), dict)
        else {}
    )
    if removed_rejected:
        rejected = _bounded_rejected_table_audit(removed_rejected)
    else:
        rejected = (
            dict(audit.get("rejected") or {})
            if isinstance(audit.get("rejected"), dict)
            else {
                "count": 0,
                "reason_counts": {},
                "samples": [],
                "samples_truncated": False,
            }
        )

    accepted_samples: list[dict[str, Any]] = []
    for raw in removed_manifest:
        if not isinstance(raw, dict) or len(accepted_samples) >= 5:
            continue
        accepted_samples.append(
            {
                key: value
                for key, value in {
                    "table_id": str(raw.get("table_id") or ""),
                    "sha256": str(raw.get("sha256") or ""),
                    "source_locator": str(raw.get("source_locator") or ""),
                    "heading": str(raw.get("heading") or ""),
                    "columns": int(raw.get("columns") or 0),
                    "rows": int(raw.get("rows") or 0),
                    "priority_for_import": bool(raw.get("priority_for_import")),
                }.items()
                if value not in {"", 0, False}
            }
        )
    existing_accepted_samples = (
        list(audit.get("accepted_samples") or [])
        if isinstance(audit.get("accepted_samples"), list)
        else []
    )
    if not accepted_samples:
        accepted_samples = [
            dict(item) for item in existing_accepted_samples[:5] if isinstance(item, dict)
        ]

    accepted_count = int(
        audit.get("accepted_count")
        or len(removed_manifest)
        or compacted.get("table_count")
        or 0
    )
    rejected_count = int(rejected.get("count") or 0)
    compacted["table_candidate_audit"] = {
        "schema_version": TABLE_CANDIDATE_AUDIT_SCHEMA_VERSION,
        "detected_count": int(audit.get("detected_count") or accepted_count + rejected_count),
        "accepted_count": accepted_count,
        "priority_imported_count": int(
            audit.get("priority_imported_count")
            or len(compacted.get("table_evidence") or [])
        ),
        "accepted_samples": accepted_samples,
        "rejected": rejected,
    }
    return compacted, {
        "rejected_table_candidates_removed": len(removed_rejected),
        "accepted_table_manifest_entries_removed": len(removed_manifest),
    }


def _compact_full_text_enrichment(
    enrichment: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    compacted = dict(enrichment or {})
    non_text = compacted.get("non_text")
    if isinstance(non_text, dict):
        compacted["non_text"], stats = compact_non_text_audit(non_text)
        return compacted, stats
    return compacted, {
        "rejected_table_candidates_removed": 0,
        "accepted_table_manifest_entries_removed": 0,
    }


def _compact_extraction_quality(
    quality: dict[str, Any] | None,
) -> tuple[dict[str, Any], int]:
    compacted = dict(quality or {})
    reports_removed = 0
    for field in ("full_text", "pdf_extraction"):
        report = compacted.pop(field, None)
        if not isinstance(report, dict):
            continue
        compacted[f"{field}_summary"] = extraction_report_summary(report)
        reports_removed += 1

    # Document conversion reports for office documents used to be copied
    # wholesale into extraction_quality.  Keep small conversion-run metadata,
    # but summarize any report that contains extracted spans or non-text data.
    conversion = compacted.get("document_conversion")
    if isinstance(conversion, dict) and (
        isinstance(conversion.get("evidence_spans"), list)
        or isinstance(conversion.get("non_text"), dict)
        or "full_text_chars" in conversion
    ):
        compacted["document_conversion"] = extraction_report_summary(conversion)
        reports_removed += 1
    return compacted, reports_removed


def compact_project_for_persistence(project: dict[str, Any]) -> dict[str, Any]:
    """Compact one copied project payload before its durable write.

    Scientific source text and canonical evidence spans remain in the
    PaperGraph record.  Only rejected fragments, redundant reports, and exact
    compatibility-view duplicates are removed.
    """

    if not isinstance(project, dict):
        return project
    stats = {
        "paper_records": 0,
        "rejected_table_candidates_removed": 0,
        "accepted_table_manifest_entries_removed": 0,
        "duplicate_extraction_reports_removed": 0,
        "duplicate_binding_assessments_removed": 0,
        "duplicate_evidence_assessments_removed": 0,
    }
    paper_by_id: dict[str, dict[str, Any]] = {}
    for record in project.get("papergraph", []) if isinstance(project.get("papergraph"), list) else []:
        if not isinstance(record, dict):
            continue
        stats["paper_records"] += 1
        paper_id = str(record.get("paper_id") or "")
        if paper_id:
            paper_by_id[paper_id] = record
        compact_record_v2_evidence(record)
        enrichment, enrichment_stats = _compact_full_text_enrichment(
            record.get("full_text_enrichment")
            if isinstance(record.get("full_text_enrichment"), dict)
            else {}
        )
        if enrichment:
            record["full_text_enrichment"] = enrichment
        stats["rejected_table_candidates_removed"] += enrichment_stats[
            "rejected_table_candidates_removed"
        ]
        stats["accepted_table_manifest_entries_removed"] += enrichment_stats[
            "accepted_table_manifest_entries_removed"
        ]
        quality, reports_removed = _compact_extraction_quality(
            record.get("extraction_quality")
            if isinstance(record.get("extraction_quality"), dict)
            else {}
        )
        record["extraction_quality"] = quality
        stats["duplicate_extraction_reports_removed"] += reports_removed

        canonical_alignment = (
            record.get("alignment_assessment")
            if isinstance(record.get("alignment_assessment"), dict)
            else None
        )
        for binding in (
            record.get("subhypothesis_bindings")
            if isinstance(record.get("subhypothesis_bindings"), list)
            else []
        ):
            if not isinstance(binding, dict):
                continue
            bound_alignment = binding.get("alignment_assessment")
            if (
                canonical_alignment is not None
                and isinstance(bound_alignment, dict)
                and _same_json(bound_alignment, canonical_alignment)
            ):
                binding.pop("alignment_assessment", None)
                binding["alignment_assessment_ref"] = "papergraph.alignment_assessment"
                stats["duplicate_binding_assessments_removed"] += 1

    # Evidence is a compatibility projection.  Keep its evidence-specific
    # fields, but reference exact copies already present in PaperGraph.
    for evidence in project.get("evidence", []) if isinstance(project.get("evidence"), list) else []:
        if not isinstance(evidence, dict):
            continue
        paper_id = str(evidence.get("paper_id") or "")
        canonical = paper_by_id.get(paper_id)
        if not canonical:
            continue
        removed_fields: list[str] = []
        for field in (
            "alignment_assessment",
            "paper_genre",
            "foundational_bridge_assessment",
        ):
            if field in evidence and field in canonical and _same_json(evidence[field], canonical[field]):
                evidence.pop(field, None)
                removed_fields.append(field)
        if removed_fields:
            evidence["canonical_record_ref"] = {
                "paper_id": paper_id,
                "fields": removed_fields,
            }
            stats["duplicate_evidence_assessments_removed"] += len(removed_fields)
        assertions = (
            canonical.get("evidence_assertions_v2")
            if isinstance(canonical.get("evidence_assertions_v2"), list)
            else []
        )
        evidence["source_span_refs"] = assertion_source_span_ids(assertions)

    previous = (
        project.get("storage_compaction")
        if isinstance(project.get("storage_compaction"), dict)
        else {}
    )
    project["storage_compaction"] = {
        "schema_version": PROJECT_STORAGE_COMPACTION_SCHEMA_VERSION,
        "canonical_full_text_report": "papergraph.full_text_enrichment",
        "evidence_projection_policy": "exact_duplicates_replaced_by_paper_id_reference",
        "rejected_fragment_policy": "counts_hashes_and_locations_only",
        "source_text_preserved": True,
        "cumulative_removed": {
            key: max(
                int((previous.get("cumulative_removed") or {}).get(key) or 0),
                int(value or 0),
            )
            for key, value in stats.items()
            if key != "paper_records"
        },
    }
    return project


def compact_project_size_fingerprint(project: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic diagnostics useful in tests and migration tools."""

    rendered = _canonical_json(project).encode("utf-8")
    return {
        "schema_version": PROJECT_STORAGE_COMPACTION_SCHEMA_VERSION,
        "bytes": len(rendered),
        "sha256": sha256(rendered).hexdigest(),
    }
