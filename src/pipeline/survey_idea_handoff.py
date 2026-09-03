"""Versioned contracts shared by Survey and Idea agents.

This module deliberately contains no agent or LLM code.  It defines the data
boundary for a future Survey -> Idea handoff, including the detailed gap
ledger, the compact handoff projection, and the run manifest that binds the
artifacts together.  Builders return JSON-compatible dictionaries so older
runtime components can adopt the contract without importing dataclass types.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Iterable, Mapping, Sequence


SURVEY_GAP_LEDGER_SCHEMA_VERSION = "survey_gap_ledger_v1"
SURVEY_IDEA_HANDOFF_SCHEMA_VERSION = "survey_idea_handoff_v1"
SURVEY_MANIFEST_SCHEMA_VERSION = "survey_manifest_v1"

GAP_STATUSES = frozenset(
    {
        "open",
        "partially_covered",
        "evidence_qualified",
        "resolved",
        "out_of_scope",
        "pending_verification",
        "rejected",
    }
)
GAP_PRIORITIES = frozenset({"high", "medium", "low"})
GAP_SUPPORT_LEVELS = frozenset(
    {"authoritative", "explicit", "cross_source", "speculative"}
)
GAP_DECISIONS = frozenset({"accept", "downgrade", "merge", "reject", "pending_verification"})
HANDOFF_STATUSES = frozenset({"ready", "partial", "rejected", "invalid"})
MANIFEST_STATUSES = frozenset({"completed", "partial", "failed", "in_progress"})
REQUIRED_MANIFEST_ARTIFACTS = frozenset(
    {
        "survey_markdown",
        "survey_json",
        "project_context",
        "evidence_plan",
        "claim_traceability",
        "gap_ledger",
        "idea_handoff",
    }
)

EVIDENCE_ROLES = frozenset(
    {
        "DIRECT_OBSERVATION",
        "MECHANISTIC_EVIDENCE",
        "COMPARATIVE_EVIDENCE",
        "BOUNDARY_EVIDENCE",
        "COUNTEREVIDENCE",
        "FORMAL_PROOF",
        "METHOD_OR_MEASUREMENT",
        "BACKGROUND_CONTEXT",
        "HYPOTHESIS_GENERATING",
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _canonicalize(value: Any) -> Any:
    """Convert supported values into deterministic JSON-compatible values."""

    if hasattr(value, "to_payload") and callable(value.to_payload):
        return _canonicalize(value.to_payload())
    if is_dataclass(value):
        return _canonicalize({item.name: getattr(value, item.name) for item in fields(value)})
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonicalize(item) for item in value), key=lambda item: repr(item))
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise ValueError("NaN and infinite values are not valid contract values.")
    return value


def canonical_json(value: Any) -> str:
    """Return stable JSON suitable for IDs and content fingerprints."""

    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_fingerprint(value: Any, *, exclude_fields: Iterable[str] = ()) -> str:
    """Hash a canonical payload, optionally excluding self-referential fields."""

    excluded = {str(item) for item in exclude_fields}
    payload = _canonicalize(value)
    if isinstance(payload, dict):
        payload = {key: item for key, item in payload.items() if key not in excluded}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def topic_fingerprint(topic: Any) -> str:
    """Return a stable fingerprint for a topic independent of outer JSON shape."""

    normalized = " ".join(_text(topic).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _id_segment(value: Any) -> str:
    segment = re.sub(r"[^A-Za-z0-9]+", "_", _text(value)).strip("_").lower()
    return segment or "unknown"


def stable_identifier(prefix: str, *parts: Any, digest_length: int = 12) -> str:
    """Build a readable, deterministic identifier from semantic parts."""

    normalized_parts = [_text(part) for part in parts]
    readable = ":".join([_id_segment(prefix), *(_id_segment(part) for part in normalized_parts)])
    digest = canonical_fingerprint(normalized_parts)[: max(6, int(digest_length))]
    return f"{readable}:{digest}"


def build_gap_id(
    subhypothesis_id: Any,
    gap_kind: Any,
    target_slot: Any,
    *,
    target_object: Any = "",
    boundary: Any = "",
) -> str:
    return stable_identifier(
        "gap",
        subhypothesis_id,
        gap_kind,
        target_slot,
        target_object,
        boundary,
    )


def build_anchor_id(
    anchor_type: Any,
    *,
    subhypothesis_id: Any = "",
    target_slot: Any = "",
    source_id: Any = "",
    claim_anchor: Any = "",
) -> str:
    return stable_identifier(
        "anchor",
        anchor_type,
        subhypothesis_id,
        target_slot,
        source_id,
        claim_anchor,
    )


def build_evidence_role_id(
    subhypothesis_id: Any,
    target_slot: Any,
    expected_role: Any,
) -> str:
    return stable_identifier("evidence", subhypothesis_id, target_slot, expected_role)


def build_handoff_id(project_id: Any, survey_run_id: Any) -> str:
    return stable_identifier("handoff", project_id, survey_run_id)


def build_ledger_id(project_id: Any, survey_run_id: Any) -> str:
    return stable_identifier("ledger", project_id, survey_run_id)


@dataclass(frozen=True)
class SourcePointer:
    artifact: str
    json_pointer: str
    paper_id: str = ""
    section: str = ""
    page: int | None = None
    paragraph_index: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact": _text(self.artifact),
            "json_pointer": _text(self.json_pointer),
        }
        for key, value in (
            ("paper_id", self.paper_id),
            ("section", self.section),
            ("page", self.page),
            ("paragraph_index", self.paragraph_index),
        ):
            if value not in (None, ""):
                payload[key] = value
        return payload


@dataclass(frozen=True)
class EvidenceEligibility:
    required_roles: list[str] = field(default_factory=list)
    allowed_claim_modes: list[str] = field(default_factory=list)
    forbidden_paper_ids: list[str] = field(default_factory=list)
    direct_writing_blocked_paper_ids: list[str] = field(default_factory=list)
    claim_limits: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "required_roles": _texts(self.required_roles),
            "allowed_claim_modes": _texts(self.allowed_claim_modes),
            "forbidden_paper_ids": _texts(self.forbidden_paper_ids),
            "direct_writing_blocked_paper_ids": _texts(self.direct_writing_blocked_paper_ids),
            "claim_limits": _texts(self.claim_limits),
        }


@dataclass(frozen=True)
class GapRecord:
    gap_id: str
    subhypothesis_id: str
    gap_kind: str
    target_slot: str
    statement: str
    status: str = "open"
    priority: str = "medium"
    support_level: str = "explicit"
    target_object: str = ""
    why_it_matters: str = ""
    candidate_defect_tags: list[str] = field(default_factory=list)
    candidate_contribution_modes: list[str] = field(default_factory=list)
    anchor_ids: list[str] = field(default_factory=list)
    evidence_eligibility: EvidenceEligibility = field(default_factory=EvidenceEligibility)
    source_pointer: SourcePointer | None = None
    gap_group_id: str = ""
    source_kind: str = ""
    gap_audit: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        subhypothesis_id: str,
        gap_kind: str,
        target_slot: str,
        statement: str,
        target_object: str = "",
        boundary: str = "",
        **kwargs: Any,
    ) -> "GapRecord":
        return cls(
            gap_id=build_gap_id(
                subhypothesis_id,
                gap_kind,
                target_slot,
                target_object=target_object,
                boundary=boundary,
            ),
            subhypothesis_id=_text(subhypothesis_id),
            gap_kind=_text(gap_kind),
            target_slot=_text(target_slot),
            statement=_text(statement),
            target_object=_text(target_object),
            **kwargs,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "gap_id": _text(self.gap_id),
            "subhypothesis_id": _text(self.subhypothesis_id),
            "gap_kind": _text(self.gap_kind),
            "target_slot": _text(self.target_slot),
            "statement": _text(self.statement),
            "status": _text(self.status),
            "priority": _text(self.priority),
            "support_level": _text(self.support_level),
            "target_object": _text(self.target_object),
            "why_it_matters": _text(self.why_it_matters),
            "candidate_defect_tags": _texts(self.candidate_defect_tags),
            "candidate_contribution_modes": _texts(self.candidate_contribution_modes),
            "anchor_ids": _texts(self.anchor_ids),
            "evidence_eligibility": self.evidence_eligibility.to_payload(),
        }
        if self.source_pointer is not None:
            payload["source_pointer"] = self.source_pointer.to_payload()
        if self.gap_group_id:
            payload["gap_group_id"] = _text(self.gap_group_id)
        if self.source_kind:
            payload["source_kind"] = _text(self.source_kind)
        if self.gap_audit:
            payload["gap_audit"] = _canonicalize(self.gap_audit)
        return payload


@dataclass(frozen=True)
class AnchorRecord:
    anchor_id: str
    anchor_type: str
    label: str
    subhypothesis_id: str = ""
    target_slot: str = ""
    claim_anchor: str = ""
    text_excerpt: str = ""
    paper_ids: list[str] = field(default_factory=list)
    supports_gap_ids: list[str] = field(default_factory=list)
    source_pointer: SourcePointer | None = None

    @classmethod
    def create(
        cls,
        *,
        anchor_type: str,
        label: str,
        subhypothesis_id: str = "",
        target_slot: str = "",
        source_id: str = "",
        claim_anchor: str = "",
        **kwargs: Any,
    ) -> "AnchorRecord":
        return cls(
            anchor_id=build_anchor_id(
                anchor_type,
                subhypothesis_id=subhypothesis_id,
                target_slot=target_slot,
                source_id=source_id,
                claim_anchor=claim_anchor,
            ),
            anchor_type=_text(anchor_type),
            label=_text(label),
            subhypothesis_id=_text(subhypothesis_id),
            target_slot=_text(target_slot),
            claim_anchor=_text(claim_anchor),
            **kwargs,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "anchor_id": _text(self.anchor_id),
            "anchor_type": _text(self.anchor_type),
            "label": _text(self.label),
            "subhypothesis_id": _text(self.subhypothesis_id),
            "target_slot": _text(self.target_slot),
            "claim_anchor": _text(self.claim_anchor),
            "text_excerpt": _text(self.text_excerpt),
            "paper_ids": _texts(self.paper_ids),
            "supports_gap_ids": _texts(self.supports_gap_ids),
        }
        if self.source_pointer is not None:
            payload["source_pointer"] = self.source_pointer.to_payload()
        return payload


@dataclass(frozen=True)
class EvidenceRoleRecord:
    role_id: str
    subhypothesis_id: str
    target_slot: str
    expected_role: str
    paper_ids: list[str] = field(default_factory=list)
    qualified_paper_ids: list[str] = field(default_factory=list)
    background_paper_ids: list[str] = field(default_factory=list)
    allowed_support_kinds: list[str] = field(default_factory=list)
    forbidden_as_direct_evidence: list[str] = field(default_factory=list)
    claim_limits: list[str] = field(default_factory=list)
    anchor_ids: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, *, subhypothesis_id: str, target_slot: str, expected_role: str, **kwargs: Any) -> "EvidenceRoleRecord":
        return cls(
            role_id=build_evidence_role_id(subhypothesis_id, target_slot, expected_role),
            subhypothesis_id=_text(subhypothesis_id),
            target_slot=_text(target_slot),
            expected_role=_text(expected_role),
            **kwargs,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_id": _text(self.role_id),
            "subhypothesis_id": _text(self.subhypothesis_id),
            "target_slot": _text(self.target_slot),
            "expected_role": _text(self.expected_role),
            "paper_ids": _texts(self.paper_ids),
            "qualified_paper_ids": _texts(self.qualified_paper_ids),
            "background_paper_ids": _texts(self.background_paper_ids),
            "allowed_support_kinds": _texts(self.allowed_support_kinds),
            "forbidden_as_direct_evidence": _texts(self.forbidden_as_direct_evidence),
            "claim_limits": _texts(self.claim_limits),
            "anchor_ids": _texts(self.anchor_ids),
        }


@dataclass(frozen=True)
class ProfileResolution:
    status: str = "unresolved"
    source: str = ""
    primary_discipline: str = ""
    discipline_ids: list[str] = field(default_factory=list)
    openalex_field_ids: list[str] = field(default_factory=list)
    paperseek_field_ids: list[str] = field(default_factory=list)
    profile_id_hint: str = ""
    confidence: float | None = None
    requires_human_confirmation: bool = False
    unresolved_reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": _text(self.status),
            "source": _text(self.source),
            "primary_discipline": _text(self.primary_discipline),
            "discipline_ids": _texts(self.discipline_ids),
            "openalex_field_ids": _texts(self.openalex_field_ids),
            "paperseek_field_ids": _texts(self.paperseek_field_ids),
            "profile_id_hint": _text(self.profile_id_hint),
            "requires_human_confirmation": bool(self.requires_human_confirmation),
            "unresolved_reason": _text(self.unresolved_reason),
        }
        if self.confidence is not None:
            payload["confidence"] = float(self.confidence)
        return payload


@dataclass(frozen=True)
class ScopeRecord:
    research_object: list[str] = field(default_factory=list)
    phenomenon: list[str] = field(default_factory=list)
    target_conditions: list[str] = field(default_factory=list)
    population_or_system: list[str] = field(default_factory=list)
    intervention_or_perturbation: list[str] = field(default_factory=list)
    outcomes_or_readouts: list[str] = field(default_factory=list)
    spatiotemporal_scope: list[str] = field(default_factory=list)
    comparators: list[str] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    claim_strength: str = "qualified"

    def to_payload(self) -> dict[str, Any]:
        return {
            "research_object": _texts(self.research_object),
            "phenomenon": _texts(self.phenomenon),
            "target_conditions": _texts(self.target_conditions),
            "population_or_system": _texts(self.population_or_system),
            "intervention_or_perturbation": _texts(self.intervention_or_perturbation),
            "outcomes_or_readouts": _texts(self.outcomes_or_readouts),
            "spatiotemporal_scope": _texts(self.spatiotemporal_scope),
            "comparators": _texts(self.comparators),
            "in_scope": _texts(self.in_scope),
            "out_of_scope": _texts(self.out_of_scope),
            "claim_strength": _text(self.claim_strength),
        }


@dataclass(frozen=True)
class GapLedger:
    project_id: str
    survey_run_id: str
    project_context_fingerprint: str
    gaps: list[GapRecord] = field(default_factory=list)
    profile_resolution: ProfileResolution = field(default_factory=ProfileResolution)
    coverage_matrix_version: str = "survey_gap_coverage_v1"
    candidate_gaps: list[GapRecord] = field(default_factory=list)
    source_artifacts: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    ledger_id: str = ""
    ledger_fingerprint: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SURVEY_GAP_LEDGER_SCHEMA_VERSION,
            "ledger_id": self.ledger_id or build_ledger_id(self.project_id, self.survey_run_id),
            "project_id": _text(self.project_id),
            "survey_run_id": _text(self.survey_run_id),
            "project_context_fingerprint": _text(self.project_context_fingerprint),
            "profile_resolution": self.profile_resolution.to_payload(),
            "coverage_matrix_version": _text(self.coverage_matrix_version),
            "gaps": [gap.to_payload() for gap in self.gaps],
            "candidate_gaps": [gap.to_payload() for gap in self.candidate_gaps],
            "source_artifacts": _canonicalize(self.source_artifacts),
            "created_at": _text(self.created_at),
        }
        if self.ledger_fingerprint:
            payload["ledger_fingerprint"] = _text(self.ledger_fingerprint)
        return payload


@dataclass(frozen=True)
class SurveyIdeaHandoff:
    project_id: str
    survey_run_id: str
    topic: str
    project_context_fingerprint: str
    gaps: list[GapRecord] = field(default_factory=list)
    anchors: list[AnchorRecord] = field(default_factory=list)
    evidence_roles: list[EvidenceRoleRecord] = field(default_factory=list)
    profile_resolution: ProfileResolution = field(default_factory=ProfileResolution)
    scope: ScopeRecord = field(default_factory=ScopeRecord)
    constraints: dict[str, Any] = field(default_factory=dict)
    gap_triage: dict[str, Any] = field(default_factory=dict)
    source_artifacts: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    status: str = "ready"
    handoff_id: str = ""
    topic_fingerprint: str = ""
    handoff_fingerprint: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SURVEY_IDEA_HANDOFF_SCHEMA_VERSION,
            "handoff_id": self.handoff_id or build_handoff_id(self.project_id, self.survey_run_id),
            "survey_run_id": _text(self.survey_run_id),
            "project_id": _text(self.project_id),
            "topic": _text(self.topic),
            "topic_fingerprint": self.topic_fingerprint or topic_fingerprint(self.topic),
            "project_context_fingerprint": _text(self.project_context_fingerprint),
            "profile_resolution": self.profile_resolution.to_payload(),
            "scope": self.scope.to_payload(),
            "gaps": [gap.to_payload() for gap in self.gaps],
            "anchors": [anchor.to_payload() for anchor in self.anchors],
            "evidence_roles": [role.to_payload() for role in self.evidence_roles],
            "constraints": _canonicalize(self.constraints),
            "gap_triage": _canonicalize(self.gap_triage),
            "source_artifacts": _canonicalize(self.source_artifacts),
            "created_at": _text(self.created_at),
            "status": _text(self.status),
        }
        if self.handoff_fingerprint:
            payload["handoff_fingerprint"] = _text(self.handoff_fingerprint)
        return payload


@dataclass(frozen=True)
class ArtifactManifestEntry:
    path: str
    sha256: str
    required: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "path": _text(self.path),
            "sha256": _text(self.sha256).lower(),
            "required": bool(self.required),
        }


@dataclass(frozen=True)
class SurveyManifest:
    survey_run_id: str
    project_id: str
    topic: str
    base_dir: str
    artifacts: dict[str, ArtifactManifestEntry] = field(default_factory=dict)
    status: str = "completed"
    project_context_fingerprint: str = ""
    topic_fingerprint: str = ""
    created_at: str = ""
    completed_at: str = ""
    handoff_schema_version: str = SURVEY_IDEA_HANDOFF_SCHEMA_VERSION
    gap_ledger_schema_version: str = SURVEY_GAP_LEDGER_SCHEMA_VERSION
    manifest_fingerprint: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SURVEY_MANIFEST_SCHEMA_VERSION,
            "survey_run_id": _text(self.survey_run_id),
            "project_id": _text(self.project_id),
            "topic": _text(self.topic),
            "topic_fingerprint": self.topic_fingerprint or topic_fingerprint(self.topic),
            "project_context_fingerprint": _text(self.project_context_fingerprint),
            "status": _text(self.status),
            "base_dir": _text(self.base_dir),
            "created_at": _text(self.created_at),
            "completed_at": _text(self.completed_at),
            "handoff_schema_version": _text(self.handoff_schema_version),
            "gap_ledger_schema_version": _text(self.gap_ledger_schema_version),
            "artifacts": {
                _text(name): entry.to_payload()
                for name, entry in sorted(self.artifacts.items(), key=lambda pair: str(pair[0]))
            },
        }
        if self.manifest_fingerprint:
            payload["manifest_fingerprint"] = _text(self.manifest_fingerprint)
        return payload


def build_gap_ledger_payload(ledger: GapLedger) -> dict[str, Any]:
    payload = ledger.to_payload()
    payload["ledger_fingerprint"] = canonical_fingerprint(
        payload,
        exclude_fields={"ledger_fingerprint"},
    )
    return payload


def build_handoff_payload(handoff: SurveyIdeaHandoff) -> dict[str, Any]:
    payload = handoff.to_payload()
    payload["handoff_fingerprint"] = canonical_fingerprint(
        payload,
        exclude_fields={"handoff_fingerprint"},
    )
    return payload


def build_manifest_payload(manifest: SurveyManifest) -> dict[str, Any]:
    payload = manifest.to_payload()
    payload["manifest_fingerprint"] = canonical_fingerprint(
        payload,
        exclude_fields={"manifest_fingerprint"},
    )
    return payload


def _required_text(payload: Mapping[str, Any], key: str, path: str, errors: list[str]) -> None:
    if not _text(payload.get(key)):
        errors.append(f"{path}.{key} must be a non-empty string")


def _check_list(payload: Mapping[str, Any], key: str, path: str, errors: list[str]) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list")
        return []
    return value


def _check_source_pointer(payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, Mapping):
        errors.append(f"{path} must be an object")
        return
    _required_text(payload, "artifact", path, errors)
    _required_text(payload, "json_pointer", path, errors)


def _check_gap(payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, Mapping):
        errors.append(f"{path} must be an object")
        return
    for key in ("gap_id", "subhypothesis_id", "gap_kind", "target_slot", "statement"):
        _required_text(payload, key, path, errors)
    status = _text(payload.get("status"))
    if status not in GAP_STATUSES:
        errors.append(f"{path}.status is unsupported: {status!r}")
    priority = _text(payload.get("priority"))
    if priority not in GAP_PRIORITIES:
        errors.append(f"{path}.priority is unsupported: {priority!r}")
    support_level = _text(payload.get("support_level"))
    if support_level not in GAP_SUPPORT_LEVELS:
        errors.append(f"{path}.support_level is unsupported: {support_level!r}")
    for key in ("candidate_defect_tags", "candidate_contribution_modes", "anchor_ids"):
        _check_list(payload, key, path, errors)
    eligibility = payload.get("evidence_eligibility")
    if not isinstance(eligibility, Mapping):
        errors.append(f"{path}.evidence_eligibility must be an object")
    else:
        for key in (
            "required_roles",
            "allowed_claim_modes",
            "forbidden_paper_ids",
            "direct_writing_blocked_paper_ids",
            "claim_limits",
        ):
            _check_list(eligibility, key, f"{path}.evidence_eligibility", errors)
        for role in eligibility.get("required_roles", []):
            if _text(role) not in EVIDENCE_ROLES:
                errors.append(f"{path}.evidence_eligibility.required_roles has unsupported role: {role!r}")
    if payload.get("source_pointer") is not None:
        _check_source_pointer(payload.get("source_pointer"), f"{path}.source_pointer", errors)


def _check_anchor(payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, Mapping):
        errors.append(f"{path} must be an object")
        return
    for key in ("anchor_id", "anchor_type", "label"):
        _required_text(payload, key, path, errors)
    for key in ("paper_ids", "supports_gap_ids"):
        _check_list(payload, key, path, errors)
    if payload.get("source_pointer") is not None:
        _check_source_pointer(payload.get("source_pointer"), f"{path}.source_pointer", errors)


def _check_evidence_role(payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, Mapping):
        errors.append(f"{path} must be an object")
        return
    for key in ("role_id", "subhypothesis_id", "target_slot", "expected_role"):
        _required_text(payload, key, path, errors)
    if _text(payload.get("expected_role")) not in EVIDENCE_ROLES:
        errors.append(f"{path}.expected_role is unsupported: {payload.get('expected_role')!r}")
    for key in (
        "paper_ids",
        "qualified_paper_ids",
        "background_paper_ids",
        "allowed_support_kinds",
        "forbidden_as_direct_evidence",
        "claim_limits",
        "anchor_ids",
    ):
        _check_list(payload, key, path, errors)


def _check_profile(payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, Mapping):
        errors.append(f"{path} must be an object")
        return
    status = _text(payload.get("status"))
    if status not in {"resolved", "ambiguous", "unresolved", "out_of_scope", "rejected", ""}:
        errors.append(f"{path}.status is unsupported: {status!r}")
    for key in ("discipline_ids", "openalex_field_ids", "paperseek_field_ids"):
        _check_list(payload, key, path, errors)
    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            errors.append(f"{path}.confidence must be between 0 and 1")


def validate_gap_ledger_payload(payload: Any, *, verify_fingerprint: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    if payload.get("schema_version") != SURVEY_GAP_LEDGER_SCHEMA_VERSION:
        errors.append("schema_version must be survey_gap_ledger_v1")
    for key in ("project_id", "survey_run_id", "project_context_fingerprint"):
        _required_text(payload, key, "payload", errors)
    _check_profile(payload.get("profile_resolution", {}), "payload.profile_resolution", errors)
    profile = payload.get("profile_resolution")
    if isinstance(profile, Mapping) and _text(profile.get("status")) in {"unresolved", "out_of_scope"}:
        if _text(profile.get("profile_id_hint")) == "computational_algorithmic":
            errors.append("unresolved/out_of_scope profile cannot use computational_algorithmic hint")
    gaps = _check_list(payload, "gaps", "payload", errors)
    candidates = _check_list(payload, "candidate_gaps", "payload", errors)
    seen: set[str] = set()
    for index, gap in enumerate([*gaps, *candidates]):
        path = f"payload.gaps[{index}]" if index < len(gaps) else f"payload.candidate_gaps[{index - len(gaps)}]"
        _check_gap(gap, path, errors)
        if isinstance(gap, Mapping):
            gap_id = _text(gap.get("gap_id"))
            if gap_id and gap_id in seen:
                errors.append(f"duplicate gap_id: {gap_id}")
            if gap_id:
                seen.add(gap_id)
    if verify_fingerprint:
        expected = _text(payload.get("ledger_fingerprint"))
        if not expected:
            errors.append("payload.ledger_fingerprint is required when verifying fingerprint")
        elif expected != canonical_fingerprint(payload, exclude_fields={"ledger_fingerprint"}):
            errors.append("ledger_fingerprint does not match canonical payload")
    return errors


def validate_handoff_payload(payload: Any, *, verify_fingerprint: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    if payload.get("schema_version") != SURVEY_IDEA_HANDOFF_SCHEMA_VERSION:
        errors.append("schema_version must be survey_idea_handoff_v1")
    for key in ("handoff_id", "survey_run_id", "project_id", "topic", "project_context_fingerprint"):
        _required_text(payload, key, "payload", errors)
    topic_hash = _text(payload.get("topic_fingerprint"))
    if not topic_hash:
        errors.append("payload.topic_fingerprint must be a non-empty string")
    elif topic_hash != topic_fingerprint(payload.get("topic")):
        errors.append("payload.topic_fingerprint does not match topic")
    status = _text(payload.get("status"))
    if status not in HANDOFF_STATUSES:
        errors.append(f"payload.status is unsupported: {status!r}")
    _check_profile(payload.get("profile_resolution", {}), "payload.profile_resolution", errors)
    profile = payload.get("profile_resolution")
    if isinstance(profile, Mapping) and _text(profile.get("status")) in {"unresolved", "out_of_scope"}:
        if _text(profile.get("profile_id_hint")) == "computational_algorithmic":
            errors.append("unresolved/out_of_scope profile cannot use computational_algorithmic hint")
    if not isinstance(payload.get("scope"), Mapping):
        errors.append("payload.scope must be an object")
    for key in ("gaps", "anchors", "evidence_roles"):
        values = _check_list(payload, key, "payload", errors)
        seen: set[str] = set()
        for index, item in enumerate(values):
            if key == "gaps":
                _check_gap(item, f"payload.gaps[{index}]", errors)
                item_id = _text(item.get("gap_id")) if isinstance(item, Mapping) else ""
            elif key == "anchors":
                _check_anchor(item, f"payload.anchors[{index}]", errors)
                item_id = _text(item.get("anchor_id")) if isinstance(item, Mapping) else ""
            else:
                _check_evidence_role(item, f"payload.evidence_roles[{index}]", errors)
                item_id = _text(item.get("role_id")) if isinstance(item, Mapping) else ""
            if item_id and item_id in seen:
                errors.append(f"duplicate {key} identifier: {item_id}")
            if item_id:
                seen.add(item_id)
    gap_ids = {
        _text(item.get("gap_id"))
        for item in payload.get("gaps", [])
        if isinstance(item, Mapping) and _text(item.get("gap_id"))
    }
    anchor_ids = {
        _text(item.get("anchor_id"))
        for item in payload.get("anchors", [])
        if isinstance(item, Mapping) and _text(item.get("anchor_id"))
    }
    for index, gap in enumerate(payload.get("gaps", [])):
        if not isinstance(gap, Mapping):
            continue
        for anchor_id in gap.get("anchor_ids", []):
            if _text(anchor_id) and _text(anchor_id) not in anchor_ids:
                errors.append(
                    f"payload.gaps[{index}].anchor_ids references unknown anchor: {_text(anchor_id)}"
                )
    for index, anchor in enumerate(payload.get("anchors", [])):
        if not isinstance(anchor, Mapping):
            continue
        for gap_id in anchor.get("supports_gap_ids", []):
            if _text(gap_id) and _text(gap_id) not in gap_ids:
                errors.append(
                    f"payload.anchors[{index}].supports_gap_ids references unknown gap: {_text(gap_id)}"
                )
    if verify_fingerprint:
        expected = _text(payload.get("handoff_fingerprint"))
        if not expected:
            errors.append("payload.handoff_fingerprint is required when verifying fingerprint")
        elif expected != canonical_fingerprint(payload, exclude_fields={"handoff_fingerprint"}):
            errors.append("handoff_fingerprint does not match canonical payload")
    return errors


def validate_manifest_payload(payload: Any, *, verify_fingerprint: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    if payload.get("schema_version") != SURVEY_MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version must be survey_manifest_v1")
    for key in ("survey_run_id", "project_id", "topic", "base_dir"):
        _required_text(payload, key, "payload", errors)
    status = _text(payload.get("status"))
    if status not in MANIFEST_STATUSES:
        errors.append(f"payload.status is unsupported: {status!r}")
    if status == "completed":
        _required_text(payload, "project_context_fingerprint", "payload", errors)
    topic_hash = _text(payload.get("topic_fingerprint"))
    if not topic_hash:
        errors.append("payload.topic_fingerprint must be a non-empty string")
    elif topic_hash != topic_fingerprint(payload.get("topic")):
        errors.append("payload.topic_fingerprint does not match topic")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("payload.artifacts must be an object")
    else:
        if status == "completed":
            missing = sorted(REQUIRED_MANIFEST_ARTIFACTS - {_text(name) for name in artifacts})
            if missing:
                errors.append(
                    "completed manifest is missing required artifacts: " + ", ".join(missing)
                )
        for name, entry in artifacts.items():
            path = f"payload.artifacts[{name!r}]"
            if not isinstance(entry, Mapping):
                errors.append(f"{path} must be an object")
                continue
            _required_text(entry, "path", path, errors)
            digest = _text(entry.get("sha256"))
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                errors.append(f"{path}.sha256 must be a 64-character hexadecimal digest")
            if not isinstance(entry.get("required"), bool):
                errors.append(f"{path}.required must be boolean")
    if payload.get("status") == "completed" and not _text(payload.get("completed_at")):
        errors.append("completed manifest requires completed_at")
    if verify_fingerprint:
        expected = _text(payload.get("manifest_fingerprint"))
        if not expected:
            errors.append("payload.manifest_fingerprint is required when verifying fingerprint")
        elif expected != canonical_fingerprint(payload, exclude_fields={"manifest_fingerprint"}):
            errors.append("manifest_fingerprint does not match canonical payload")
    return errors


def assert_valid_payload(payload: Any, contract: str, *, verify_fingerprint: bool = False) -> None:
    validators = {
        SURVEY_GAP_LEDGER_SCHEMA_VERSION: validate_gap_ledger_payload,
        SURVEY_IDEA_HANDOFF_SCHEMA_VERSION: validate_handoff_payload,
        SURVEY_MANIFEST_SCHEMA_VERSION: validate_manifest_payload,
    }
    validator = validators.get(_text(contract))
    if validator is None:
        raise ValueError(f"Unsupported Survey contract: {contract!r}")
    errors = validator(payload, verify_fingerprint=verify_fingerprint)
    if errors:
        raise ValueError("Invalid contract payload: " + "; ".join(errors))


_SOURCE_POINTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["artifact", "json_pointer"],
    "properties": {
        "artifact": {"type": "string", "minLength": 1},
        "json_pointer": {"type": "string", "minLength": 1},
        "paper_id": {"type": "string"},
        "section": {"type": "string"},
        "page": {"type": ["integer", "null"]},
        "paragraph_index": {"type": ["integer", "null"]},
    },
}

_GAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "gap_id",
        "subhypothesis_id",
        "gap_kind",
        "target_slot",
        "statement",
        "status",
        "priority",
        "support_level",
        "candidate_defect_tags",
        "candidate_contribution_modes",
        "anchor_ids",
        "evidence_eligibility",
    ],
    "properties": {
        "gap_id": {"type": "string", "minLength": 1},
        "subhypothesis_id": {"type": "string", "minLength": 1},
        "gap_kind": {"type": "string", "minLength": 1},
        "target_slot": {"type": "string", "minLength": 1},
        "statement": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": sorted(GAP_STATUSES)},
        "priority": {"type": "string", "enum": sorted(GAP_PRIORITIES)},
        "support_level": {"type": "string", "enum": sorted(GAP_SUPPORT_LEVELS)},
        "candidate_defect_tags": {"type": "array", "items": {"type": "string"}},
        "candidate_contribution_modes": {"type": "array", "items": {"type": "string"}},
        "anchor_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_eligibility": {"type": "object"},
        "source_pointer": _SOURCE_POINTER_SCHEMA,
        "gap_audit": {"type": "object"},
    },
}

SURVEY_GAP_LEDGER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Gap Ledger v1",
    "type": "object",
    "required": [
        "schema_version",
        "ledger_id",
        "project_id",
        "survey_run_id",
        "project_context_fingerprint",
        "profile_resolution",
        "gaps",
        "candidate_gaps",
    ],
    "properties": {
        "schema_version": {"const": SURVEY_GAP_LEDGER_SCHEMA_VERSION},
        "ledger_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "survey_run_id": {"type": "string", "minLength": 1},
        "project_context_fingerprint": {"type": "string", "minLength": 1},
        "profile_resolution": {"type": "object"},
        "coverage_matrix_version": {"type": "string"},
        "gaps": {"type": "array", "items": _GAP_SCHEMA},
        "candidate_gaps": {"type": "array", "items": _GAP_SCHEMA},
        "source_artifacts": {"type": "object"},
        "created_at": {"type": "string"},
        "ledger_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

SURVEY_IDEA_HANDOFF_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey to Idea Handoff v1",
    "type": "object",
    "required": [
        "schema_version",
        "handoff_id",
        "survey_run_id",
        "project_id",
        "topic",
        "topic_fingerprint",
        "project_context_fingerprint",
        "profile_resolution",
        "scope",
        "gaps",
        "anchors",
        "evidence_roles",
        "constraints",
        "source_artifacts",
        "status",
    ],
    "properties": {
        "schema_version": {"const": SURVEY_IDEA_HANDOFF_SCHEMA_VERSION},
        "handoff_id": {"type": "string", "minLength": 1},
        "survey_run_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "topic": {"type": "string", "minLength": 1},
        "topic_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "project_context_fingerprint": {"type": "string", "minLength": 1},
        "profile_resolution": {"type": "object"},
        "scope": {"type": "object"},
        "gaps": {"type": "array", "items": _GAP_SCHEMA},
        "anchors": {"type": "array", "items": {"type": "object"}},
        "evidence_roles": {"type": "array", "items": {"type": "object"}},
        "constraints": {"type": "object"},
        "gap_triage": {"type": "object"},
        "source_artifacts": {"type": "object"},
        "created_at": {"type": "string"},
        "status": {"type": "string", "enum": sorted(HANDOFF_STATUSES)},
        "handoff_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

SURVEY_MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Run Manifest v1",
    "type": "object",
    "required": [
        "schema_version",
        "survey_run_id",
        "project_id",
        "topic",
        "topic_fingerprint",
        "status",
        "base_dir",
        "artifacts",
        "handoff_schema_version",
        "gap_ledger_schema_version",
    ],
    "properties": {
        "schema_version": {"const": SURVEY_MANIFEST_SCHEMA_VERSION},
        "survey_run_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "topic": {"type": "string", "minLength": 1},
        "topic_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "project_context_fingerprint": {"type": "string"},
        "status": {"type": "string", "enum": sorted(MANIFEST_STATUSES)},
        "base_dir": {"type": "string", "minLength": 1},
        "created_at": {"type": "string"},
        "completed_at": {"type": "string"},
        "handoff_schema_version": {"const": SURVEY_IDEA_HANDOFF_SCHEMA_VERSION},
        "gap_ledger_schema_version": {"const": SURVEY_GAP_LEDGER_SCHEMA_VERSION},
        "artifacts": {"type": "object"},
        "manifest_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

CONTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    SURVEY_GAP_LEDGER_SCHEMA_VERSION: SURVEY_GAP_LEDGER_SCHEMA,
    SURVEY_IDEA_HANDOFF_SCHEMA_VERSION: SURVEY_IDEA_HANDOFF_SCHEMA,
    SURVEY_MANIFEST_SCHEMA_VERSION: SURVEY_MANIFEST_SCHEMA,
}


__all__ = [
    "ArtifactManifestEntry",
    "AnchorRecord",
    "CONTRACT_SCHEMAS",
    "EVIDENCE_ROLES",
    "EvidenceEligibility",
    "EvidenceRoleRecord",
    "GapLedger",
    "GapRecord",
    "ProfileResolution",
    "ScopeRecord",
    "SourcePointer",
    "SurveyIdeaHandoff",
    "SurveyManifest",
    "SURVEY_GAP_LEDGER_SCHEMA",
    "SURVEY_GAP_LEDGER_SCHEMA_VERSION",
    "SURVEY_IDEA_HANDOFF_SCHEMA",
    "SURVEY_IDEA_HANDOFF_SCHEMA_VERSION",
    "SURVEY_MANIFEST_SCHEMA",
    "SURVEY_MANIFEST_SCHEMA_VERSION",
    "REQUIRED_MANIFEST_ARTIFACTS",
    "assert_valid_payload",
    "build_anchor_id",
    "build_evidence_role_id",
    "build_gap_id",
    "build_gap_ledger_payload",
    "build_handoff_id",
    "build_handoff_payload",
    "build_ledger_id",
    "build_manifest_payload",
    "canonical_fingerprint",
    "canonical_json",
    "stable_identifier",
    "topic_fingerprint",
    "validate_gap_ledger_payload",
    "validate_handoff_payload",
    "validate_manifest_payload",
]
