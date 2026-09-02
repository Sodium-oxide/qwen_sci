"""Governance metadata for evidence-bounded scientific-gap candidates.

The gap detector intentionally produces several different kinds of objects:
author-stated open questions, inferred but corpus-bounded candidates,
landscape opportunities, and extraction shortages.  This module gives those
objects a stable identity and an explicit claim boundary so downstream agents
cannot describe a PaperGraph absence as a field-wide scientific fact.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any
import re
import time


GAP_CLAIM_SCHEMA_VERSION = "gap_claim_v1"
GAP_CANDIDATE_IDENTITY_SCHEMA_VERSION = "gap_candidate_identity_v1"
GAP_CANDIDATE_LEDGER_SCHEMA_VERSION = "gap_candidate_ledger_v1"
GAP_IDENTITY_REGISTRY_SCHEMA_VERSION = "gap_identity_registry_v1"
GAP_PROVENANCE_SCHEMA_VERSION = "gap_provenance_v1"

LANDSCAPE_OPPORTUNITY = "LANDSCAPE_OPPORTUNITY"
COMPONENT_BRIDGE_OPPORTUNITY = "COMPONENT_BRIDGE_OPPORTUNITY"
EVIDENCE_EXTRACTION_SHORTAGE = "EVIDENCE_EXTRACTION_SHORTAGE"
MECHANISM_DISCOVERY_LEAD = "MECHANISM_DISCOVERY_LEAD"
SOURCE_STATED_OPEN_GAP = "SOURCE_STATED_OPEN_GAP"
CORPUS_BOUNDED_INFERRED_GAP = "CORPUS_BOUNDED_INFERRED_GAP"
EXTERNALLY_VERIFIED_OPEN_GAP = "EXTERNALLY_VERIFIED_OPEN_GAP"
EXTERNALLY_VERIFIED_CONTRADICTION = "EXTERNALLY_VERIFIED_CONTRADICTION"
VERIFICATION_INSUFFICIENT = "VERIFICATION_INSUFFICIENT"
RESOLVED_OR_SUPERSEDED = "RESOLVED_OR_SUPERSEDED"


def _compact(value: Any, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normal(value: Any) -> str:
    text = _compact(value).lower()
    text = re.sub(r"[^a-z0-9\u0370-\u03ff\u4e00-\u9fff_+./\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_identifier(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return text.strip("_") or "unbound"


def _gap_sequence_from_id(gap_id: Any, project_id: Any) -> int:
    prefix = f"gap_{_safe_identifier(project_id)}_"
    text = str(gap_id or "")
    if not text.startswith(prefix):
        return 0
    suffix = text[len(prefix):]
    return int(suffix) if suffix.isdigit() else 0


def _valid_candidate_identity(value: Any) -> bool:
    return bool(re.fullmatch(r"gapcand_[0-9a-f]{24}", str(value or "").strip()))


def _source_unit_ids(gap: dict[str, Any]) -> list[str]:
    units = gap.get("source_evidence_units") if isinstance(gap.get("source_evidence_units"), list) else []
    values = [
        f"{_normal(item.get('paper_id'))}:{_normal(item.get('source_unit_id'))}"
        for item in units
        if isinstance(item, dict)
        and (_normal(item.get("paper_id")) or _normal(item.get("source_unit_id")))
    ]
    return sorted(set(values))


def _causal_roles(gap: dict[str, Any]) -> dict[str, str]:
    seed_contract = (
        gap.get("mechanism_seed_contract")
        if isinstance(gap.get("mechanism_seed_contract"), dict)
        else {}
    )
    mechanism_seed = (
        seed_contract.get("mechanism_seed")
        if isinstance(seed_contract.get("mechanism_seed"), dict)
        else {}
    )

    def seed_value(role: str) -> str:
        entry = mechanism_seed.get(role) if isinstance(mechanism_seed.get(role), dict) else {}
        return _normal(entry.get("value"))

    return {
        "input": seed_value("input"),
        "mediator": seed_value("mediator"),
        "outcome": seed_value("outcome"),
    }


def build_gap_candidate_identity(gap: dict[str, Any]) -> dict[str, Any]:
    """Create a stable identity without relying on the per-run ``gap_id``.

    Source units are the strongest identity anchors.  When a candidate has not
    yet been source-bound, its normalized scientific description remains in
    the payload so it is traceable but cannot silently merge with a
    source-bound candidate from another scientific context.
    """
    item = dict(gap or {})
    roles = _causal_roles(item)
    payload = {
        "sub_hypothesis_id": _normal(item.get("sub_hypothesis_id") or item.get("subhypothesis_id")),
        "gap_type": _normal(item.get("gap_type") or item.get("type")),
        "scientific_object": _normal(item.get("scientific_object")),
        "causal_roles": roles,
        "source_units": _source_unit_ids(item),
        "description": _normal(item.get("gap_description") or item.get("description")),
    }
    serialized = "\0".join(
        [
            payload["sub_hypothesis_id"],
            payload["gap_type"],
            payload["scientific_object"],
            payload["causal_roles"]["input"],
            payload["causal_roles"]["mediator"],
            payload["causal_roles"]["outcome"],
            "|".join(payload["source_units"]),
            payload["description"],
        ]
    )
    return {
        "schema_version": GAP_CANDIDATE_IDENTITY_SCHEMA_VERSION,
        "candidate_identity": "gapcand_" + sha256(serialized.encode("utf-8")).hexdigest()[:24],
        "identity_payload": payload,
        "source_bound": bool(payload["source_units"]),
    }


def _candidate_identity_record(gap: dict[str, Any]) -> dict[str, Any]:
    """Keep a candidate's first identity record immutable across enrichment.

    A targeted retrieval normally adds source units and causal annotations.
    Those additions must improve the *same* candidate, not silently create a
    fresh identity merely because a later state has a richer description.
    """
    existing_identity = str(gap.get("candidate_identity") or "").strip()
    existing_record = (
        gap.get("candidate_identity_record")
        if isinstance(gap.get("candidate_identity_record"), dict)
        else {}
    )
    if (
        _valid_candidate_identity(existing_identity)
        and str(existing_record.get("candidate_identity") or "") == existing_identity
    ):
        return dict(existing_record)
    return build_gap_candidate_identity(gap)


def _identity_registry(project: dict[str, Any], *, now: float) -> dict[str, Any]:
    """Return the persistent candidate-identity to canonical-gap-id registry.

    ``knowledge_gaps`` deliberately excludes secondary and evidence-repair
    candidates.  An allocator seeded only from that list can therefore reuse
    an old identifier after a rerun.  This registry records every candidate
    that crossed TanXi, including rejected and repair-only candidates.
    """
    project_id = str(project.get("project_id") or "")
    raw = project.get("gap_identity_registry")
    registry = dict(raw) if isinstance(raw, dict) else {}
    assignments = registry.get("assignments")
    normalized_assignments = {
        str(identity): dict(entry)
        for identity, entry in (assignments.items() if isinstance(assignments, dict) else [])
        if _valid_candidate_identity(identity) and isinstance(entry, dict)
    }
    registry.update({
        "schema_version": GAP_IDENTITY_REGISTRY_SCHEMA_VERSION,
        "project_id": project_id,
        "assignments": normalized_assignments,
        "updated_at": float(now),
    })

    # One-time in-memory backfill from the prior ledger.  Older snapshots
    # have only ``latest_gap_id``; treat it as canonical only when the id is
    # not already claimed by another candidate identity.
    claimed: dict[str, str] = {
        str(entry.get("canonical_gap_id") or ""): identity
        for identity, entry in normalized_assignments.items()
        if str(entry.get("canonical_gap_id") or "")
    }
    prior = project.get("gap_candidate_ledger")
    prior_rows = prior.get("candidates") if isinstance(prior, dict) and isinstance(prior.get("candidates"), list) else []
    for row in prior_rows:
        if not isinstance(row, dict):
            continue
        identity = str(row.get("candidate_identity") or "")
        gap_id = str(row.get("canonical_gap_id") or row.get("latest_gap_id") or "")
        if not _valid_candidate_identity(identity) or not gap_id or identity in normalized_assignments:
            continue
        if gap_id in claimed:
            continue
        normalized_assignments[identity] = {
            "candidate_identity": identity,
            "canonical_gap_id": gap_id,
            "first_assigned_at": float(row.get("first_seen_at") or now),
            "last_seen_at": float(row.get("last_seen_at") or now),
            "observed_gap_ids": [gap_id],
            "supersedes_gap_ids": [],
            "state_versions": [],
        }
        claimed[gap_id] = identity
    registry["assignments"] = normalized_assignments
    return registry


def _known_project_gap_ids(project: dict[str, Any], registry: dict[str, Any]) -> set[str]:
    ids = {
        str(entry.get("canonical_gap_id") or "")
        for entry in (registry.get("assignments") or {}).values()
        if isinstance(entry, dict) and str(entry.get("canonical_gap_id") or "")
    }
    for item in project.get("knowledge_gaps", []) or []:
        if isinstance(item, dict) and str(item.get("gap_id") or ""):
            ids.add(str(item.get("gap_id")))
    for row in ((project.get("gap_candidate_ledger") or {}).get("candidates") or []):
        if isinstance(row, dict):
            for key in ("canonical_gap_id", "latest_gap_id"):
                if str(row.get(key) or ""):
                    ids.add(str(row.get(key)))
    return ids


def assign_gap_candidate_provenance(
    project: dict[str, Any],
    gap: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Attach one immutable candidate identity and one non-reusable gap id.

    The supplied ``gap_id`` is treated as an observed legacy/run-local id. It
    is retained as an alias when necessary, but no longer decides identity.
    All downstream artifacts can join safely on
    ``(candidate_identity, state_version)`` while existing callers continue
    to use the canonical ``gap_id`` field.
    """
    timestamp = float(now if now is not None else time.time())
    item = gap
    identity_record = _candidate_identity_record(item)
    identity = str(identity_record.get("candidate_identity") or "")
    if not _valid_candidate_identity(identity):
        identity_record = build_gap_candidate_identity(item)
        identity = str(identity_record["candidate_identity"])
    registry = _identity_registry(project, now=timestamp)
    assignments = registry["assignments"]
    known_ids = _known_project_gap_ids(project, registry)
    observed_gap_id = str(item.get("gap_id") or "").strip()
    assignment = assignments.get(identity)
    if not isinstance(assignment, dict):
        # Preserve a first unique legacy id during migration.  If another
        # identity already owns it, allocate a never-before-used canonical id.
        owner_by_id = {
            str(entry.get("canonical_gap_id") or ""): candidate_identity
            for candidate_identity, entry in assignments.items()
            if isinstance(entry, dict) and str(entry.get("canonical_gap_id") or "")
        }
        canonical_gap_id = observed_gap_id if observed_gap_id and observed_gap_id not in owner_by_id else ""
        if not canonical_gap_id:
            project_id = str(project.get("project_id") or item.get("project_id") or "")
            maximum = max(
                [_gap_sequence_from_id(value, project_id) for value in known_ids] + [0]
            )
            next_sequence = max(
                int(project.get("next_gap_sequence") or 1),
                int(registry.get("next_gap_sequence") or 1),
                maximum + 1,
            )
            while True:
                candidate_id = f"gap_{_safe_identifier(project_id)}_{next_sequence:04d}"
                next_sequence += 1
                if candidate_id not in known_ids and candidate_id not in owner_by_id:
                    canonical_gap_id = candidate_id
                    break
            registry["next_gap_sequence"] = next_sequence
            project["next_gap_sequence"] = next_sequence
        assignment = {
            "candidate_identity": identity,
            "canonical_gap_id": canonical_gap_id,
            "first_assigned_at": timestamp,
            "last_seen_at": timestamp,
            "observed_gap_ids": [],
            "supersedes_gap_ids": [],
            "state_versions": [],
        }
        assignments[identity] = assignment

    canonical_gap_id = str(assignment.get("canonical_gap_id") or "")
    observed_ids = [str(value) for value in (assignment.get("observed_gap_ids") or []) if str(value)]
    if observed_gap_id and observed_gap_id not in observed_ids:
        observed_ids.append(observed_gap_id)
    if canonical_gap_id and canonical_gap_id not in observed_ids:
        observed_ids.append(canonical_gap_id)
    supersedes = [str(value) for value in (assignment.get("supersedes_gap_ids") or []) if str(value)]
    if observed_gap_id and observed_gap_id != canonical_gap_id and observed_gap_id not in supersedes:
        supersedes.append(observed_gap_id)
    state_version = int(project.get("state_version") or 0)
    state_versions = [int(value) for value in (assignment.get("state_versions") or []) if str(value).isdigit()]
    if state_version and state_version not in state_versions:
        state_versions.append(state_version)
    assignment.update({
        "candidate_identity": identity,
        "canonical_gap_id": canonical_gap_id,
        "last_seen_at": timestamp,
        "observed_gap_ids": observed_ids[-80:],
        "supersedes_gap_ids": supersedes[-80:],
        "supersedes_gap_id": supersedes[-1] if supersedes else "",
        "state_versions": state_versions[-80:],
    })
    registry["updated_at"] = timestamp
    project["gap_identity_registry"] = registry
    item["candidate_identity"] = identity
    item["candidate_identity_record"] = identity_record
    item["gap_id"] = canonical_gap_id
    item["gap_provenance"] = {
        "schema_version": GAP_PROVENANCE_SCHEMA_VERSION,
        "candidate_identity": identity,
        "canonical_gap_id": canonical_gap_id,
        "observed_gap_id": observed_gap_id,
        "supersedes_gap_ids": list(supersedes),
        "supersedes_gap_id": supersedes[-1] if supersedes else "",
        "state_version": state_version,
    }
    return item


def assign_gap_candidate_provenance_batch(
    project: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Canonicalize a batch in deterministic order without id re-use."""
    timestamp = float(now if now is not None else time.time())
    ordered = [item for item in candidates if isinstance(item, dict)]
    # Sorting by the immutable identity makes collision repair independent of
    # list order, a requirement for replayed/staged TanXi runs.
    ordered.sort(key=lambda item: str(_candidate_identity_record(item).get("candidate_identity") or ""))
    for item in ordered:
        assign_gap_candidate_provenance(project, item, now=timestamp)
    return candidates


def rebuild_gap_identity_migration(
    project: dict[str, Any],
    snapshots: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Reconstruct immutable identity mappings from historical snapshots.

    Each snapshot supplies ``state_version`` and a ``candidates`` list.  The
    earliest observed *candidate* keeps its first gap id as canonical; a
    later candidate carrying a recycled id is allocated a new canonical id.
    Historical files are not rewritten.  Instead this emits an explicit map
    from every observed ``(snapshot, gap_id)`` to
    ``(candidate_identity, canonical_gap_id)`` so their logs remain auditable.
    """
    timestamp = float(now if now is not None else time.time())
    original_state_version = int(project.get("state_version") or 0)
    observed: list[dict[str, Any]] = []
    ordered_snapshots = sorted(
        [snapshot for snapshot in snapshots if isinstance(snapshot, dict)],
        key=lambda snapshot: int(snapshot.get("state_version") or 0),
    )
    for snapshot_index, snapshot in enumerate(ordered_snapshots):
        snapshot_version = int(snapshot.get("state_version") or 0)
        if snapshot_version:
            project["state_version"] = snapshot_version
        for ordinal, raw in enumerate(snapshot.get("candidates") or []):
            if not isinstance(raw, dict):
                continue
            candidate = dict(raw)
            observed_gap_id = str(candidate.get("gap_id") or "")
            assign_gap_candidate_provenance(project, candidate, now=timestamp + snapshot_index / 1000 + ordinal / 100000)
            provenance = candidate.get("gap_provenance") if isinstance(candidate.get("gap_provenance"), dict) else {}
            observed.append({
                "state_version": snapshot_version,
                "snapshot_id": str(snapshot.get("snapshot_id") or f"snapshot_{snapshot_index + 1:04d}"),
                "observed_gap_id": observed_gap_id,
                "candidate_identity": str(candidate.get("candidate_identity") or ""),
                "canonical_gap_id": str(candidate.get("gap_id") or ""),
                "supersedes_gap_id": str(provenance.get("supersedes_gap_id") or ""),
            })
    project["state_version"] = max(
        [original_state_version] + [int(snapshot.get("state_version") or 0) for snapshot in ordered_snapshots]
    )
    by_identity: dict[str, dict[str, Any]] = {}
    for record in observed:
        identity = str(record.get("candidate_identity") or "")
        if not identity:
            continue
        entry = by_identity.setdefault(identity, {
            "candidate_identity": identity,
            "canonical_gap_id": str(record.get("canonical_gap_id") or ""),
            "observations": [],
        })
        entry["observations"].append(dict(record))
    migration = {
        "schema_version": "gap_id_snapshot_migration_v1",
        "project_id": str(project.get("project_id") or ""),
        "generated_at": timestamp,
        "snapshot_count": len(ordered_snapshots),
        "observation_count": len(observed),
        "candidates": sorted(by_identity.values(), key=lambda item: str(item.get("candidate_identity") or "")),
        "observed_id_map": observed,
    }
    project["gap_id_snapshot_migration"] = migration
    return migration


def build_gap_claim(gap: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """State exactly what a candidate may claim from its current evidence.

    The claim level is intentionally independent from the workflow track.  A
    candidate can be ready for a *project-local* primary hypothesis while its
    statement about field-wide novelty remains source- or corpus-bounded.
    """
    item = dict(gap or {})
    pool = str(item.get("gap_candidate_pool") or "")
    track = str(item.get("gap_track") or "")
    epistemic = item.get("gap_epistemic_verdict") if isinstance(item.get("gap_epistemic_verdict"), dict) else {}
    audit = item.get("gap_epistemic_audit") if isinstance(item.get("gap_epistemic_audit"), dict) else {}
    verification = item.get("gap_existence_verification") if isinstance(item.get("gap_existence_verification"), dict) else {}
    verdict = str(verification.get("verdict") or "")
    epistemic_verdict = str(epistemic.get("verdict") or "")
    audit_category = str(audit.get("category") or "")
    explicit_assessment = audit.get("explicit_predicate_assessment") if isinstance(audit.get("explicit_predicate_assessment"), dict) else {}
    explicit = bool(
        epistemic_verdict == "EXPLICIT_AUTHOR_STATED_GAP"
        or audit_category.startswith("author_stated")
        or explicit_assessment.get("passes") is True
    )
    verified_at = verification.get("verified_at") or verification.get("executed_at") or ""
    scope = verification.get("verification_scope") if isinstance(verification.get("verification_scope"), dict) else {}

    if verdict == "RESOLVED_IN_LITERATURE":
        level = RESOLVED_OR_SUPERSEDED
        statement = "Aligned retrieval contains a direct resolution claim; do not present this candidate as an open gap."
    elif verdict == "AUTHOR_STATED_OPEN_GAP":
        level = EXTERNALLY_VERIFIED_OPEN_GAP
        statement = "An aligned externally retrieved source explicitly describes the scoped relation as open or unresolved."
    elif verdict == "CONTRADICTORY_EVIDENCE":
        level = EXTERNALLY_VERIFIED_CONTRADICTION
        statement = "Aligned external retrieval reports conflicting evidence for the scoped relation."
    elif verdict == "CORPUS_BOUNDED_UNRESOLVED":
        level = CORPUS_BOUNDED_INFERRED_GAP
        statement = "The executed retrieval scope did not identify a direct resolution claim; this is not proof of field-wide absence."
    elif verdict == "INSUFFICIENT_RETRIEVAL":
        level = VERIFICATION_INSUFFICIENT
        statement = "Retrieval was insufficient to state whether the scoped relation remains open."
    elif pool == "EVIDENCE_EXTRACTION_SHORTAGE_POOL":
        level = EVIDENCE_EXTRACTION_SHORTAGE
        statement = "The project lacks an adequately bound source unit; this is an evidence-repair task, not a scientific gap claim."
    elif str(item.get("gap_type") or "") == "component_bridge_gap_synthesis" or track == "COMPONENT_BRIDGE_GAP_SYNTHESIS":
        level = COMPONENT_BRIDGE_OPPORTUNITY
        statement = "This is restricted component/bridge context for a follow-up hypothesis, not direct-core or field-wide gap evidence."
    elif explicit:
        level = SOURCE_STATED_OPEN_GAP
        statement = "A source-bound fragment states a scoped unknown, limitation, or open problem; current field-wide status is unverified."
    elif pool == "LANDSCAPE_DIAGNOSTIC_POOL" or track == "SECONDARY_RESEARCH_OPPORTUNITY":
        level = LANDSCAPE_OPPORTUNITY
        statement = "This is a PaperGraph coverage or exploration opportunity, not a claim that the field lacks the relation."
    elif pool == "MECHANISM_DISCOVERY_LEAD_POOL":
        level = MECHANISM_DISCOVERY_LEAD
        statement = "The candidate needs upstream evidence or entity resolution before it may be described as a scientific gap."
    else:
        level = CORPUS_BOUNDED_INFERRED_GAP
        statement = "This is an inferred, evidence-bounded candidate and must not be described as a field-wide knowledge absence."

    return {
        "schema_version": GAP_CLAIM_SCHEMA_VERSION,
        "claim_level": level,
        "statement": statement,
        "workflow_track": track,
        "source_bound": bool(_source_unit_ids(item)),
        "explicit_source_predicate": explicit,
        "verification_verdict": verdict or "NOT_RUN",
        "last_verified_at": verified_at,
        "verification_scope": scope,
        "may_be_stated_as_field_wide_gap": False,
        "requires_external_verification": level in {
            SOURCE_STATED_OPEN_GAP,
            CORPUS_BOUNDED_INFERRED_GAP,
            VERIFICATION_INSUFFICIENT,
        },
        "updated_at": float(now if now is not None else time.time()),
    }


def annotate_gap_governance(gap: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    item = dict(gap or {})
    identity = _candidate_identity_record(item)
    item["candidate_identity"] = identity["candidate_identity"]
    item["candidate_identity_record"] = identity
    item["gap_claim"] = build_gap_claim(item, now=now)
    return item


def reconcile_gap_candidate_ledger(
    project: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Merge current candidates into a project-local, non-destructive ledger."""
    timestamp = float(now if now is not None else time.time())
    previous = project.get("gap_candidate_ledger") if isinstance(project.get("gap_candidate_ledger"), dict) else {}
    previous_rows = previous.get("candidates") if isinstance(previous.get("candidates"), list) else []
    previous_by_identity = {
        str(row.get("candidate_identity") or ""): row
        for row in previous_rows
        if isinstance(row, dict) and str(row.get("candidate_identity") or "")
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Allocate before writing the ledger.  This mutates the candidate objects
    # carried by the TanXi report, so logs, tasks, and persisted candidate
    # pools all observe the same canonical id rather than a run-local one.
    assign_gap_candidate_provenance_batch(project, candidates, now=timestamp)
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = annotate_gap_governance(raw, now=timestamp)
        identity = str(item.get("candidate_identity") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        prior = previous_by_identity.get(identity, {})
        claim = item.get("gap_claim") if isinstance(item.get("gap_claim"), dict) else {}
        identity_record = item.get("candidate_identity_record") if isinstance(item.get("candidate_identity_record"), dict) else {}
        provenance = item.get("gap_provenance") if isinstance(item.get("gap_provenance"), dict) else {}
        assignment = (
            ((project.get("gap_identity_registry") or {}).get("assignments") or {}).get(identity)
            if isinstance(project.get("gap_identity_registry"), dict)
            else {}
        )
        rows.append({
            "candidate_identity": identity,
            "first_seen_at": float(prior.get("first_seen_at") or timestamp),
            "last_seen_at": timestamp,
            "canonical_gap_id": str(provenance.get("canonical_gap_id") or item.get("gap_id") or ""),
            # Kept for older consumers.  Unlike the old implementation, it
            # now always equals canonical_gap_id rather than a rerun-local id.
            "latest_gap_id": str(provenance.get("canonical_gap_id") or item.get("gap_id") or ""),
            "last_observed_gap_id": str(provenance.get("observed_gap_id") or ""),
            "supersedes_gap_ids": list(
                (assignment or {}).get("supersedes_gap_ids")
                or provenance.get("supersedes_gap_ids")
                or []
            ),
            "supersedes_gap_id": str(
                (assignment or {}).get("supersedes_gap_id")
                or provenance.get("supersedes_gap_id")
                or ""
            ),
            "state_versions": list((assignment or {}).get("state_versions") or []),
            "gap_type": str(item.get("gap_type") or ""),
            "gap_track": str(item.get("gap_track") or ""),
            "candidate_pool": str(item.get("gap_candidate_pool") or ""),
            "claim_level": str(claim.get("claim_level") or ""),
            "verification_verdict": str(claim.get("verification_verdict") or "NOT_RUN"),
            "last_verified_at": claim.get("last_verified_at") or "",
            "source_bound": bool(identity_record.get("source_bound")),
            "source_unit_count": len((identity_record.get("identity_payload") or {}).get("source_units") or []),
        })
    rows.sort(key=lambda row: (str(row.get("candidate_identity") or ""), str(row.get("latest_gap_id") or "")))
    return {
        "schema_version": GAP_CANDIDATE_LEDGER_SCHEMA_VERSION,
        "updated_at": timestamp,
        "candidate_count": len(rows),
        "candidates": rows,
    }
