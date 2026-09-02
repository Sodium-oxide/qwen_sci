"""Source-bound, edge-level evidence graph for scientific gap detection.

This module is deliberately independent of the older candidate generators.
It turns an already extracted causal graph into a typed, auditable evidence
graph and detects gaps *between evidence edges*.  It never creates a
scientific candidate from a title, a lexical matrix hole, or an unbound LLM
statement.

The public payloads are dictionaries because project artifacts are persisted
as JSON.  The dataclasses define the invariant at the Python boundary and make
that persisted shape explicit without coupling this module to pipeline state.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from itertools import combinations
from typing import Any, Iterable
import json
import re

try:
    from ._gap_types import (
        CandidateStage,
        GapLifecyclePhase,
        GapSignalType,
        GapType,
        contract_for,
        initial_gap_assessment,
        normalize_gap_subtype,
        synchronize_candidate_surface,
    )
    from ._research_question_contract import validate_research_question_contract
    from ._evidence_assertions import (
        HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
    )
    from ._evidence_recovery import classify_evidence_recovery
    from ._research_graph import (
        DetectionContext,
        RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        build_research_evidence_graph,
        detection_context_ref,
        _validated_detection_context_for_runtime,
    )
except ImportError:
    from _gap_types import (
        CandidateStage,
        GapLifecyclePhase,
        GapSignalType,
        GapType,
        contract_for,
        initial_gap_assessment,
        normalize_gap_subtype,
        synchronize_candidate_surface,
    )
    from _research_question_contract import validate_research_question_contract
    from _evidence_assertions import (
        HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
    )
    from _evidence_recovery import classify_evidence_recovery
    from _research_graph import (
        DetectionContext,
        RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        build_research_evidence_graph,
        detection_context_ref,
        _validated_detection_context_for_runtime,
    )


EVIDENCE_GRAPH_SCHEMA_VERSION = "source_bound_evidence_graph_v2"
GAP_CANDIDATE_SCHEMA_VERSION = "gap_candidate_v2"
SOURCE_BOUND_GAP_CANDIDATE_FACTORY_SCHEMA_VERSION = "source_bound_gap_candidate_factory_v3"
GAP_DETECTION_PROVENANCE_SCHEMA_VERSION = "gap_detection_provenance_v3"
SOURCE_BOUND_GAP_EVIDENCE_BUNDLE_SCHEMA_VERSION = "source_bound_gap_evidence_bundle_v3"
GAP_CANDIDATES_DISCOVERED = "GAP_CANDIDATES_DISCOVERED"
GAP_NOT_RECOVERED_FROM_EVIDENCE = "GAP_NOT_RECOVERED_FROM_EVIDENCE"
INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS = "INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS"
SH_SCOPE_OR_OBJECT_MISMATCH = "SH_SCOPE_OR_OBJECT_MISMATCH"
UNSUPPORTED_SPECULATIVE_CHAIN = "UNSUPPORTED_SPECULATIVE_CHAIN"
NO_EVIDENCE_OF_GAP_IN_SUFFICIENT_CORPUS = "NO_EVIDENCE_OF_GAP_IN_SUFFICIENT_CORPUS"

_EVIDENCE_ROLES = frozenset(
    {
        "BACKGROUND",
        "OBSERVATION",
        "ASSOCIATION",
        "INTERVENTION",
        "MECHANISTIC_SUPPORT",
        "CONTRADICTION",
        "LIMITATION",
        "EXPLICIT_UNKNOWN",
        "BOUNDARY_CONDITION",
        "METHOD_LIMITATION",
    }
)
_EPISTEMIC_STATUSES = frozenset(
    {
        "AUTHOR_STATED",
        "SOURCE_EXTRACTED",
        "MODEL_DERIVED",
        "INFERRED_PROXY",
        "UNRESOLVED",
    }
)

_LOW_INFORMATION_WORDS = frozenset(
    {
        "a", "an", "and", "as", "at", "be", "both", "by", "can", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "their", "this", "to",
        "under", "via", "with", "without", "which", "who", "whose", "within",
        "effect", "effects", "entity", "factor", "mechanism", "model", "outcome",
        "pathway", "process", "response", "result", "results", "signal", "state",
        "study", "studies", "system", "systems", "unknown", "variable", "variables",
        "analysis", "approach", "data", "evidence", "method", "methods", "research",
        "theory", "thing", "things",
    }
)

_RELATIONAL_CLAUSE_RE = re.compile(
    r"\b(?:affect(?:s|ed|ing)?|associate(?:s|d|ing)?|caus(?:e|es|ed|ing)|"
    r"control(?:s|led|ling)?|correlat(?:e|es|ed|ing)|define(?:s|d|ing)?|"
    r"determin(?:e|es|ed|ing)|driv(?:e|es|en|ing)|explain(?:s|ed|ing)?|"
    r"increas(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|influenc(?:e|es|ed|ing)|"
    r"lead(?:s|ing)?\s+to|mediate(?:s|d|ing)?|predict(?:s|ed|ing)?|"
    r"promot(?:e|es|ed|ing)|reduc(?:e|es|ed|ing)|regulat(?:e|es|ed|ing)|"
    r"result(?:s|ed|ing)?\s+in|suppress(?:es|ed|ing)?|"
    r"影响|导致|介导|促进|抑制|调控|决定|关联|增加|减少|预测|解释)",
    re.IGNORECASE,
)
_GAP_PREDICATE_RE = re.compile(
    r"\b(?:remain(?:s)?\s+(?:unknown|unclear|unresolved|unexplained)|"
    r"(?:is|are)\s+(?:unknown|unclear|unresolved)|"
    r"not\s+(?:well\s+)?(?:understood|established|tested|evaluated|examined|investigated)|"
    r"has\s+not\s+been\s+(?:established|tested|evaluated|examined|investigated)|"
    r"conflict(?:ing)?\s+(?:evidence|result|results)|contradict(?:ory|ion)|"
    r"insufficient\s+evidence|lack\s+of\s+evidence|open\s+(?:problem|question)|"
    r"limited\s+by|major\s+limitation|key\s+limitation|"
    r"尚不清楚|仍不清楚|尚未建立|未被证实|未验证|证据不足|结果矛盾|存在争议|有待阐明)",
    re.IGNORECASE,
)
_FORWARD_TEMPORAL_RE = re.compile(
    r"\b(?:before|after|subsequent(?:ly)?|then|later|followed\s+by|precedes?|"
    r"prior\s+to|thereafter|time[- ]lag)\b|(?:之前|之后|随后|继而|先于|晚于)",
    re.IGNORECASE,
)
_POSITIVE_POLARITY_RE = re.compile(
    r"\b(?:increase(?:s|d)?|improve(?:s|d)?|promote(?:s|d)?|enhance(?:s|d)?|"
    r"activate(?:s|d)?|positive(?:ly)?)\b|(?:增加|提高|促进|增强|激活)",
    re.IGNORECASE,
)
_NEGATIVE_POLARITY_RE = re.compile(
    r"\b(?:decrease(?:s|d)?|reduce(?:s|d)?|inhibit(?:s|ed)?|suppress(?:es|ed)?|"
    r"impair(?:s|ed)?|negative(?:ly)?)\b|(?:减少|降低|抑制|阻碍|损害)",
    re.IGNORECASE,
)
_PROXY_OR_INFERENCE_RE = re.compile(
    r"\b(?:proxy|surrogate|inferred|estimate(?:d)?|model(?:led|ed)?|predicted|potential|simulated)\b|"
    r"(?:代理指标|推断|估计|预测|潜力|模拟)",
    re.IGNORECASE,
)
_COMPETING_MECHANISM_RE = re.compile(
    r"\b(?:alternative|competing|distinct|multiple)\s+(?:mechanism|pathway|explanation)|"
    r"\b(?:cannot|unable to)\s+distinguish\b|\bconsistent\s+with\s+both\b|"
    r"(?:竞争机制|替代机制|多种机制|无法区分|难以区分|均可解释)",
    re.IGNORECASE,
)
_CONTEXT_DIMENSIONS = (
    "research_object",
    "species_or_system",
    "model_or_sample",
    "stage_or_regime",
    "timepoint",
    "method",
    "spatial_scale",
    "temporal_scale",
    "environmental_context",
    "intervention_context",
    "measurement_definition",
    "outcome_definition",
    "transfer_justification",
)


@dataclass(frozen=True)
class SourceEvidenceUnit:
    paper_id: str
    source_unit_id: str
    excerpt_hash: str
    excerpt: str
    binding_status: str
    source_field: str = ""
    source_location: dict[str, Any] = field(default_factory=dict)
    source_locator: str = ""
    sub_hypothesis_id: str = ""
    source_type: str = "fulltext"
    section: str = ""
    span_start: int | None = None
    span_end: int | None = None
    study_system: str = ""
    conditions: dict[str, str] = field(default_factory=dict)
    evidence_role: str = "OBSERVATION"
    epistemic_status: str = "SOURCE_EXTRACTED"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtomicEntity:
    label: str
    canonical_label: str
    entity_type: str
    specificity_score: int
    valid: bool
    reason: str
    scope: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtomicCausalEdge:
    edge_id: str
    source: AtomicEntity
    target: AtomicEntity
    relation: str
    paper_id: str
    citation: str
    sub_hypothesis_id: str
    source_evidence: SourceEvidenceUnit
    context: dict[str, str]
    evidence_type: str
    polarity: str
    claim_mode: str
    time_order: str
    evidence_ids: list[str]
    support_strength: str
    uncertainty: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source"] = self.source.as_dict()
        payload["target"] = self.target.as_dict()
        payload["source_evidence"] = self.source_evidence.as_dict()
        return payload


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(value: Any) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_+./-]*|[\u4e00-\u9fff]+|\d+(?:\.\d+)?", _clean(value).lower())


def canonical_entity_key(value: Any) -> str:
    text = _clean(value).lower().replace("β", " beta ").replace("α", " alpha ")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _content_tokens(value: Any) -> list[str]:
    return [token for token in _tokenize(value) if token not in _LOW_INFORMATION_WORDS]


def assess_atomic_entity(value: Any, *, role: str = "") -> AtomicEntity:
    """Validate a graph node before it can participate in a scientific edge.

    This is structural rather than field-specific.  It rejects grammatical
    clauses and low-information placeholders, but does not require a curated
    ontology for an unfamiliar scientific object.
    """
    label = _clean(value)
    key = canonical_entity_key(label)
    tokens = _content_tokens(label)
    if not label or not key:
        return AtomicEntity(label, key, "UNKNOWN", 0, False, "ENTITY_EMPTY")
    if key in _LOW_INFORMATION_WORDS or not tokens:
        return AtomicEntity(label, key, "LOW_INFORMATION", 0, False, "ENTITY_LOW_INFORMATION")
    if len(label) > 240:
        return AtomicEntity(label, key, "RELATIONAL_CLAUSE", len(tokens), False, "ENTITY_TOO_LONG")
    if _RELATIONAL_CLAUSE_RE.search(label) and len(tokens) >= 3:
        return AtomicEntity(label, key, "RELATIONAL_CLAUSE", len(tokens), False, "ENTITY_IS_RELATION_CLAUSE")
    if re.search(r"[.?!;]\s", label) and len(tokens) >= 5:
        return AtomicEntity(label, key, "RELATIONAL_CLAUSE", len(tokens), False, "ENTITY_IS_SENTENCE")
    lowered = label.lower()
    if any(marker in lowered for marker in ("rate", "ratio", "yield", "density", "flux", "level", "score", "count", "%", "率", "水平", "浓度", "通量")):
        entity_type = "MEASURABLE_READOUT"
    elif any(marker in lowered for marker in ("temperature", "pressure", "concentration", "dose", "time", "温度", "压力", "浓度", "剂量", "时间")):
        entity_type = "CONDITION_OR_INPUT"
    else:
        entity_type = "SCIENTIFIC_ENTITY"
    return AtomicEntity(label, key, entity_type, len(tokens), True, "ENTITY_ATOMIC")


def _source_location_value(value: Any, *keys: str) -> str:
    mapping = value if isinstance(value, dict) else {}
    for key in keys:
        candidate = _clean(mapping.get(key))
        if candidate:
            return candidate
    return ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _evidence_role(value: dict[str, Any], *, excerpt: str, source_field: str) -> str:
    explicit = _clean(value.get("evidence_role")).upper()
    if explicit in _EVIDENCE_ROLES:
        return explicit
    text = " ".join((_clean(source_field), excerpt, _clean(value.get("evidence_type")))).lower()
    if _GAP_PREDICATE_RE.search(excerpt):
        return "EXPLICIT_UNKNOWN"
    if any(term in text for term in ("contradict", "conflicting", "inconsistent", "矛盾", "争议")):
        return "CONTRADICTION"
    if any(term in text for term in ("limitation", "limited", "bias", "unable", "局限", "限制")):
        return "METHOD_LIMITATION" if "method" in text else "LIMITATION"
    if any(term in text for term in ("boundary", "threshold", "only under", "condition-dependent", "边界", "阈值", "仅在")):
        return "BOUNDARY_CONDITION"
    if any(term in text for term in ("intervention", "perturb", "knockout", "randomized", "experimental", "干预", "扰动")):
        return "INTERVENTION"
    if any(term in text for term in ("mechanism", "mediated", "pathway", "mechanistic", "机制", "介导")):
        return "MECHANISTIC_SUPPORT"
    if any(term in text for term in ("association", "correlation", "correlate", "相关", "关联")):
        return "ASSOCIATION"
    return "OBSERVATION"


def _epistemic_status(value: dict[str, Any], *, excerpt: str) -> str:
    explicit = _clean(value.get("epistemic_status")).upper()
    if explicit in _EPISTEMIC_STATUSES:
        return explicit
    if _PROXY_OR_INFERENCE_RE.search(excerpt):
        return "INFERRED_PROXY"
    if _GAP_PREDICATE_RE.search(excerpt):
        return "AUTHOR_STATED"
    return "SOURCE_EXTRACTED"


def _source_unit_from_mapping(value: Any, *, sub_hypothesis_id: str = "") -> SourceEvidenceUnit | None:
    if not isinstance(value, dict):
        return None
    paper_id = _clean(value.get("paper_id"))
    source_unit_id = _clean(value.get("source_unit_id"))
    binding_status = _clean(value.get("binding_status"))
    if not paper_id or not source_unit_id or binding_status != "SOURCE_UNIT_VERIFIED":
        return None
    excerpt = _clean(value.get("excerpt"))
    excerpt_hash = _clean(value.get("excerpt_hash")) or sha256(excerpt.encode("utf-8")).hexdigest()[:16]
    source_location = dict(value.get("source_location") or {}) if isinstance(value.get("source_location"), dict) else {}
    source_field = _clean(value.get("source_field") or value.get("section"))
    conditions = value.get("conditions") if isinstance(value.get("conditions"), dict) else {}
    return SourceEvidenceUnit(
        paper_id=paper_id,
        source_unit_id=source_unit_id,
        excerpt_hash=excerpt_hash,
        excerpt=excerpt[:1200],
        binding_status=binding_status,
        source_field=source_field,
        source_location=source_location,
        source_locator=_clean(value.get("source_locator")) or _clean(source_location.get("source_locator") or source_location.get("locator")),
        sub_hypothesis_id=_clean(value.get("sub_hypothesis_id") or sub_hypothesis_id),
        source_type=_clean(value.get("source_type")) or "fulltext",
        section=_clean(value.get("section")) or source_field,
        span_start=_optional_int(value.get("span_start") or source_location.get("span_start") or source_location.get("sentence_start")),
        span_end=_optional_int(value.get("span_end") or source_location.get("span_end") or source_location.get("sentence_end")),
        study_system=_clean(value.get("study_system") or value.get("species_or_system") or value.get("model_or_sample")),
        conditions={str(key): _clean(item) for key, item in conditions.items() if _clean(item)},
        evidence_role=_evidence_role(value, excerpt=excerpt, source_field=source_field),
        epistemic_status=_epistemic_status(value, excerpt=excerpt),
    )


def _edge_polarity(edge: dict[str, Any]) -> str:
    explicit = _clean(edge.get("polarity")).lower()
    if explicit:
        if _POSITIVE_POLARITY_RE.search(explicit):
            return "POSITIVE"
        if _NEGATIVE_POLARITY_RE.search(explicit):
            return "NEGATIVE"
    text = " ".join(_clean(edge.get(key)) for key in ("relation", "evidence_excerpt"))
    if _POSITIVE_POLARITY_RE.search(text):
        return "POSITIVE"
    if _NEGATIVE_POLARITY_RE.search(text):
        return "NEGATIVE"
    return "UNSPECIFIED"


def _edge_context(value: Any) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    return {key: _clean(raw.get(key)) for key in _CONTEXT_DIMENSIONS if _clean(raw.get(key))}


def _edge_claim_mode(edge: dict[str, Any], unit: SourceEvidenceUnit) -> str:
    explicit = _clean(edge.get("claim_mode")).lower()
    if explicit in {"observation", "association", "intervention", "mechanism", "model"}:
        return explicit
    evidence_type = _clean(edge.get("evidence_type")).lower()
    if edge.get("interventions") or unit.evidence_role == "INTERVENTION" or any(term in evidence_type for term in ("experiment", "intervention", "perturb")):
        return "intervention"
    if unit.evidence_role == "MECHANISTIC_SUPPORT" or "mechan" in evidence_type:
        return "mechanism"
    if unit.epistemic_status in {"INFERRED_PROXY", "MODEL_DERIVED"} or "model" in evidence_type:
        return "model"
    if unit.evidence_role == "ASSOCIATION" or "associ" in evidence_type:
        return "association"
    return "observation"


def _edge_time_order(edge: dict[str, Any], unit: SourceEvidenceUnit) -> str:
    explicit = _clean(edge.get("time_order") or edge.get("temporal_order"))
    if explicit:
        return explicit
    context = edge.get("context") if isinstance(edge.get("context"), dict) else {}
    return "SOURCE_MARKED" if _FORWARD_TEMPORAL_RE.search(" ".join((unit.excerpt, _clean(context.get("timepoint"))))) else "UNRESOLVED"


def _edge_support_strength(claim_mode: str, unit: SourceEvidenceUnit) -> str:
    if claim_mode == "intervention":
        return "INTERVENTIONAL"
    if claim_mode == "mechanism":
        return "MECHANISTIC"
    if claim_mode == "association":
        return "ASSOCIATIVE"
    if unit.epistemic_status in {"INFERRED_PROXY", "MODEL_DERIVED"}:
        return "INDIRECT"
    return "OBSERVATIONAL"


def _edge_id(edge: dict[str, Any], source: AtomicEntity, target: AtomicEntity, source_unit: SourceEvidenceUnit) -> str:
    payload = "|".join((source_unit.paper_id, source_unit.source_unit_id, source.canonical_label, target.canonical_label, _clean(edge.get("relation"))))
    return f"edge_{sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def build_contextual_evidence_graph(raw_graph: Any) -> dict[str, Any]:
    """Convert a raw causal graph into source-bound atomic edges.

    Rejected raw edges remain diagnostics.  They cannot leak into cross-paper
    or cross-SH candidate generation.
    """
    graph = raw_graph if isinstance(raw_graph, dict) else {}
    raw_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    labels = {str(node.get("id") or ""): _clean(node.get("label")) for node in raw_nodes if isinstance(node, dict)}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, edge in enumerate(graph.get("edges") if isinstance(graph.get("edges"), list) else []):
        if not isinstance(edge, dict):
            continue
        relation = _clean(edge.get("relation"))
        if relation in {"observed_by", "intervenes_on"}:
            continue
        source = assess_atomic_entity(labels.get(_clean(edge.get("source"))), role="source")
        target = assess_atomic_entity(labels.get(_clean(edge.get("target"))), role="target")
        unit = _source_unit_from_mapping(edge.get("source_evidence"), sub_hypothesis_id=_clean(edge.get("sub_hypothesis_id")))
        context = _edge_context(edge.get("context"))
        if unit is not None:
            unit = SourceEvidenceUnit(
                **{
                    **unit.as_dict(),
                    "study_system": unit.study_system or context.get("species_or_system") or context.get("model_or_sample") or context.get("research_object", ""),
                    "conditions": unit.conditions or {
                        key: value for key, value in context.items()
                        if key not in {"research_object", "species_or_system", "model_or_sample"}
                    },
                }
            )
        reasons: list[str] = []
        if not source.valid:
            reasons.append(source.reason)
        if not target.valid:
            reasons.append(target.reason)
        if source.canonical_label and source.canonical_label == target.canonical_label:
            reasons.append("EDGE_SELF_LOOP")
        if unit is None:
            reasons.append("EDGE_SOURCE_UNIT_UNVERIFIED")
        if not relation:
            reasons.append("EDGE_RELATION_MISSING")
        if reasons:
            rejected.append(
                {
                    "raw_edge_index": index,
                    "reason_codes": reasons,
                    "source": source.as_dict(),
                    "target": target.as_dict(),
                    "paper_id": _clean(edge.get("paper_id")),
                    "sub_hypothesis_id": _clean(edge.get("sub_hypothesis_id")),
                }
            )
            continue
        source = AtomicEntity(
            **{
                **source.as_dict(),
                "scope": context,
                "aliases": [source.label],
                "provenance": [unit.source_unit_id],
            }
        )
        target = AtomicEntity(
            **{
                **target.as_dict(),
                "scope": context,
                "aliases": [target.label],
                "provenance": [unit.source_unit_id],
            }
        )
        claim_mode = _edge_claim_mode(edge, unit)
        atomic = AtomicCausalEdge(
            edge_id=_edge_id(edge, source, target, unit),
            source=source,
            target=target,
            relation=relation,
            paper_id=_clean(edge.get("paper_id")) or unit.paper_id,
            citation=_clean(edge.get("citation")),
            sub_hypothesis_id=_clean(edge.get("sub_hypothesis_id")) or unit.sub_hypothesis_id,
            source_evidence=unit,
            context=context,
            evidence_type=_clean(edge.get("evidence_type")) or "reported_unclassified",
            polarity=_edge_polarity(edge),
            claim_mode=claim_mode,
            time_order=_edge_time_order(edge, unit),
            evidence_ids=[unit.source_unit_id],
            support_strength=_edge_support_strength(claim_mode, unit),
            uncertainty=(
                "PROXY_OR_MODEL_DERIVATION"
                if unit.epistemic_status in {"INFERRED_PROXY", "MODEL_DERIVED"}
                else "SOURCE_BOUND_LIMITED" if unit.evidence_role in {"LIMITATION", "METHOD_LIMITATION", "EXPLICIT_UNKNOWN"}
                else "NOT_REPORTED"
            ),
        )
        if atomic.edge_id in seen:
            continue
        seen.add(atomic.edge_id)
        accepted.append(atomic.as_dict())
    entities: dict[str, dict[str, Any]] = {}
    for edge in accepted:
        for role in ("source", "target"):
            entity = edge.get(role) if isinstance(edge.get(role), dict) else {}
            key = _clean(entity.get("canonical_label"))
            if key:
                entities.setdefault(key, entity)
    return {
        "schema_version": EVIDENCE_GRAPH_SCHEMA_VERSION,
        "edges": accepted,
        "entities": list(entities.values()),
        "rejected_edges": rejected,
        "non_causal_claims": [
            dict(item)
            for item in graph.get("non_causal_claims", [])
            if isinstance(item, dict)
        ],
        "summary": {
            "raw_edge_count": len(graph.get("edges") if isinstance(graph.get("edges"), list) else []),
            "atomic_edge_count": len(accepted),
            "rejected_edge_count": len(rejected),
            "rejected_reason_counts": dict(Counter(reason for item in rejected for reason in item.get("reason_codes", []))),
        },
    }


def assess_context_compatibility(left: dict[str, Any], right: dict[str, Any], *, cross_subhypothesis: bool = False) -> dict[str, Any]:
    left_context = left.get("context") if isinstance(left.get("context"), dict) else {}
    right_context = right.get("context") if isinstance(right.get("context"), dict) else {}
    matched: list[str] = []
    conflicts: list[str] = []
    unknown: list[str] = []
    for dimension in _CONTEXT_DIMENSIONS:
        left_value = canonical_entity_key(left_context.get(dimension))
        right_value = canonical_entity_key(right_context.get(dimension))
        if left_value and right_value:
            (matched if left_value == right_value else conflicts).append(dimension)
        elif dimension not in {"method", "transfer_justification"}:
            unknown.append(dimension)
    left_branch = _clean(left.get("sub_hypothesis_id"))
    right_branch = _clean(right.get("sub_hypothesis_id"))
    branch_match = bool(left_branch and left_branch == right_branch)
    object_match = "research_object" in matched
    support_match = bool({"species_or_system", "model_or_sample", "stage_or_regime"} & set(matched))
    if cross_subhypothesis:
        compatible = bool(not conflicts and object_match and support_match)
    else:
        compatible = bool(branch_match and not conflicts and object_match and support_match)
    return {
        "compatible": compatible,
        "status": "CONTEXT_COMPATIBLE" if compatible else "CONTEXT_INCOMPATIBLE" if conflicts else "CONTEXT_UNDERDETERMINED",
        "same_sub_hypothesis": branch_match,
        "matched_dimensions": matched,
        "conflicting_dimensions": conflicts,
        "unknown_dimensions": unknown,
        "entity_compatible": object_match,
        "system_compatible": support_match,
        "condition_compatible": not bool({"stage_or_regime", "environmental_context", "intervention_context"} & set(conflicts)),
        "scale_compatible": not bool({"spatial_scale", "temporal_scale", "timepoint"} & set(conflicts)),
        "measurement_compatible": not bool({"method", "measurement_definition", "outcome_definition"} & set(conflicts)),
        "transfer_justification_present": bool(
            canonical_entity_key(left_context.get("transfer_justification"))
            or canonical_entity_key(right_context.get("transfer_justification"))
        ),
        "left_context": left_context,
        "right_context": right_context,
    }


def assess_temporal_support(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    source_text = " ".join(
        [
            _clean((left.get("source_evidence") or {}).get("excerpt")),
            _clean((right.get("source_evidence") or {}).get("excerpt")),
            _clean((left.get("context") or {}).get("timepoint")),
            _clean((right.get("context") or {}).get("timepoint")),
        ]
    )
    marker = bool(_FORWARD_TEMPORAL_RE.search(source_text))
    left_time = canonical_entity_key((left.get("context") or {}).get("timepoint"))
    right_time = canonical_entity_key((right.get("context") or {}).get("timepoint"))
    distinct_units = _clean((left.get("source_evidence") or {}).get("source_unit_id")) != _clean((right.get("source_evidence") or {}).get("source_unit_id"))
    return {
        "status": "SUPPORTED" if marker and distinct_units else "UNRESOLVED",
        "affirmative_marker_present": marker,
        "distinct_source_units": distinct_units,
        "left_timepoint": left_time,
        "right_timepoint": right_time,
    }


def _references(edges: Iterable[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for edge in edges:
        ref = _clean(edge.get("citation") or (edge.get("source_evidence") or {}).get("paper_id"))
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _source_units(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges:
        unit = edge.get("source_evidence") if isinstance(edge.get("source_evidence"), dict) else {}
        key = _clean(unit.get("source_unit_id"))
        if key and key not in seen:
            seen.add(key)
            output.append(dict(unit))
    return output


def _falsifiability_plan(
    *,
    input_label: str,
    mediator_label: str,
    outcome_label: str,
    gap_class: str,
) -> dict[str, str]:
    hypothesis = f"{mediator_label} explains the constrained relation from {input_label} to {outcome_label}."
    if gap_class == "CONTRADICTION_GAP":
        return {
            "hypothesis": hypothesis,
            "discriminating_prediction": f"Under matched conditions, the direction of {input_label} -> {outcome_label} will depend on one measurable boundary variable.",
            "prediction": f"Under matched conditions, the direction of {input_label} -> {outcome_label} will depend on one measurable boundary variable.",
            "falsifying_observation": "The direction remains unchanged across the prespecified boundary conditions.",
            "required_control": "Match the system, measurement definition, and operating regime before comparing studies or experiments.",
            "minimal_measurement_set": f"Measure {input_label}, {mediator_label or outcome_label}, and {outcome_label} with the boundary variable.",
            "competing_explanations": "A hidden difference in system, measurement definition, or operating regime explains the apparent disagreement.",
        }
    return {
        "hypothesis": hypothesis,
        "discriminating_prediction": f"If {mediator_label} is on the operative path from {input_label} to {outcome_label}, varying or measuring it under matched conditions will change the observed {outcome_label} response.",
        "prediction": f"If {mediator_label} is on the operative path from {input_label} to {outcome_label}, varying or measuring it under matched conditions will change the observed {outcome_label} response.",
        "falsifying_observation": f"After accounting for {mediator_label}, {input_label} changes {outcome_label} without the predicted mediator response.",
        "required_control": "Use matched baseline, system, operating-regime, and temporal controls; compare a mediator-preserving and mediator-disrupting condition when feasible.",
        "minimal_measurement_set": f"Measure {input_label}, {mediator_label}, and {outcome_label} in a common study context.",
        "competing_explanations": "A parallel mediator, direct effect, or unmatched condition explains the observed endpoint without the proposed edge.",
    }


def _candidate_identity(kind: str, branches: list[str], nodes: list[str], unit_ids: list[str]) -> str:
    payload = {"kind": kind, "branches": sorted(branches), "nodes": sorted(nodes), "source_units": sorted(unit_ids)}
    return f"egap_{sha256(str(payload).encode('utf-8')).hexdigest()[:20]}"


def _candidate(
    *,
    kind: str,
    gap_type: GapType,
    signal_type: GapSignalType,
    description: str,
    source_edges: list[dict[str, Any]],
    sub_hypothesis_id: str = "",
    sub_hypothesis_ids: list[str] | None = None,
    input_label: str = "",
    mediator_label: str = "",
    outcome_label: str = "",
    missing_edge: dict[str, Any] | None = None,
    compatibility: dict[str, Any] | None = None,
    predicate_evidence: dict[str, Any] | None = None,
    competing_explanations: list[str] | None = None,
    gap_subtype: str = "",
    type_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    units = _source_units(source_edges)
    branches = [item for item in (sub_hypothesis_ids or [sub_hypothesis_id]) if item]
    identity = _candidate_identity(
        kind,
        branches,
        [canonical_entity_key(input_label), canonical_entity_key(mediator_label), canonical_entity_key(outcome_label)],
        [str(unit.get("source_unit_id") or "") for unit in units],
    )
    falsifiability = _falsifiability_plan(
        input_label=input_label or "the upstream variable",
        mediator_label=mediator_label or "the proposed intermediate variable",
        outcome_label=outcome_label or "the measurable outcome",
        gap_class=kind,
    )
    if competing_explanations:
        falsifiability["competing_explanations"] = "; ".join(competing_explanations)
    scope = next(
        (
            dict((edge.get("context") or {}))
            for edge in source_edges
            if isinstance(edge, dict) and isinstance(edge.get("context"), dict)
        ),
        {},
    )
    payload = dict(type_payload or {})
    if gap_type == GapType.CAUSAL_IDENTIFICATION:
        payload.setdefault("input", input_label)
        payload.setdefault("mediator", mediator_label)
        payload.setdefault("outcome", outcome_label)
        payload.setdefault("identification_missing", _clean((missing_edge or {}).get("reason")))
        payload.setdefault("alternative_explanations", list(competing_explanations or []))
        payload.setdefault("known_relations", [
            f"{input_label} -> {mediator_label}",
            f"{mediator_label} -> {outcome_label}",
        ] if mediator_label else [f"{input_label} -> {outcome_label}"])
        payload.setdefault("identification_design", _clean(falsifiability.get("required_control")))
        payload.setdefault("falsification_plan", falsifiability)
    elif gap_type == GapType.AUTHOR_STATED_LIMITATION:
        source_signal = (predicate_evidence or {}).get("source_signal") if isinstance((predicate_evidence or {}).get("source_signal"), dict) else {}
        payload.setdefault("author_stated_unknown", _clean((predicate_evidence or {}).get("text")))
        payload.setdefault("limitation_kind", "EXPLICIT_UNKNOWN")
        payload.setdefault("affected_claim", description)
        payload.setdefault("scope_of_limitation", _clean(scope.get("research_object") or scope.get("species_or_system")))
        payload.setdefault("limitation_span_id", _clean(source_signal.get("source_unit_id")))
    elif gap_type == GapType.MEASUREMENT_OPERATIONALIZATION:
        payload.setdefault("construct", outcome_label)
        payload.setdefault("proxy_measure", input_label)
        payload.setdefault("target_measure", outcome_label)
        payload.setdefault("mapping_status", "UNVALIDATED")
        payload.setdefault("validation_missing", _clean((missing_edge or {}).get("reason")))
    elif gap_type == GapType.BOUNDARY_HETEROGENEITY:
        payload.setdefault("base_relation", f"{input_label} -> {outcome_label}")
        payload.setdefault("boundary_variable", ", ".join((compatibility or {}).get("conflicting_dimensions", [])))
        payload.setdefault("condition_a", str(((compatibility or {}).get("left_context") or {}).get("stage_or_regime") or ""))
        payload.setdefault("condition_b", str(((compatibility or {}).get("right_context") or {}).get("stage_or_regime") or ""))
        payload.setdefault("effect_difference", _clean((missing_edge or {}).get("reason")))
        payload.setdefault("threshold_unknown", True)
    elif gap_type == GapType.CONTRADICTION_REPLICATION:
        payload.setdefault("shared_claim", f"{input_label} -> {outcome_label}")
        payload.setdefault(
            "evidence_sets",
            [
                {
                    "source_ids": [str((edge.get("source_evidence") or {}).get("source_unit_id") or "")],
                    "result_direction": str(edge.get("polarity") or "UNSPECIFIED"),
                    "scope": dict(edge.get("context") or {}),
                }
                for edge in source_edges if isinstance(edge, dict)
            ],
        )
        payload.setdefault("comparability_verdict", str((compatibility or {}).get("status") or "UNASSESSED"))
        payload.setdefault("unexplained_difference", _clean((missing_edge or {}).get("reason")))
    elif gap_type == GapType.SCALE_INTEGRATION:
        payload.setdefault("source_scale", str(((compatibility or {}).get("left_context") or {}).get("spatial_scale") or ""))
        payload.setdefault("target_scale", str(((compatibility or {}).get("right_context") or {}).get("spatial_scale") or ""))
        payload.setdefault("bridge_variable", mediator_label)
        payload.setdefault("coupling_question", description)
    assessment = initial_gap_assessment(
        gap_type=gap_type,
        signal_type=signal_type,
        candidate_stage=CandidateStage.PATH_CANDIDATE if gap_type == GapType.CAUSAL_IDENTIFICATION else CandidateStage.RAW_CANDIDATE,
    )
    assessment["gap_subtype"] = gap_subtype
    candidate = {
        "schema_version": GAP_CANDIDATE_SCHEMA_VERSION,
        "candidate_identity": identity,
        "gap_type": gap_type.value,
        "gap_subtype": gap_subtype,
        "gap_class": kind,
        "gap_assessment": assessment,
        "type_payload": payload,
        "research_question": {
            "object": _clean(scope.get("research_object") or scope.get("species_or_system")),
            "known_claim": f"{input_label} -> {outcome_label}" if input_label and outcome_label else description,
            "unknown_claim": _clean((missing_edge or {}).get("reason")),
            "declared_scope": scope,
        },
        "description": description,
        "sub_hypothesis_id": sub_hypothesis_id,
        "sub_hypothesis_ids": branches,
        "source_evidence_units": units,
        "supporting_references": _references(source_edges),
        "known_edges": source_edges,
        "input": input_label,
        "mediator": mediator_label,
        "outcome": outcome_label,
        "missing_edge": dict(missing_edge or {}),
        "compatibility": dict(compatibility or {}),
        "gap_predicate_evidence": dict(predicate_evidence or {}),
        "falsifiability_plan": falsifiability,
        "competing_explanations": list(competing_explanations or []),
    }
    return synchronize_candidate_surface(candidate)


def _predicate_assessment(text: Any) -> dict[str, Any]:
    clean = _clean(text)
    return {
        "passes": bool(_GAP_PREDICATE_RE.search(clean)),
        "text": clean,
        "verdict": "EXPLICIT_SOURCE_BOUND_GAP_PREDICATE" if _GAP_PREDICATE_RE.search(clean) else "NO_EXPLICIT_GAP_PREDICATE",
    }


_AUTHOR_SIGNAL_TYPE_RULES: tuple[tuple[GapType, re.Pattern[str]], ...] = (
    (GapType.MEASUREMENT_OPERATIONALIZATION, re.compile(r"\b(?:measurement|measure|proxy|surrogate|calibrat|instrument|assay|label|readout)\b", re.IGNORECASE)),
    (GapType.CONTRADICTION_REPLICATION, re.compile(r"\b(?:contradict|conflict|inconsistent|replicat|reproduc)\b", re.IGNORECASE)),
    (GapType.BOUNDARY_HETEROGENEITY, re.compile(r"\b(?:boundary|regime|threshold|heterogen|condition-dependent|context-dependent)\b", re.IGNORECASE)),
    (GapType.THEORY_MATHEMATICAL, re.compile(r"\b(?:theorem|proof|assumption|axiom|identif(?:y|iability)|counterexample|formal)\b", re.IGNORECASE)),
    (GapType.GENERALIZATION_TRANSPORTABILITY, re.compile(r"\b(?:generaliz|transport|external validity|out-of-distribution|transfer)\b", re.IGNORECASE)),
    (GapType.METHOD_DESIGN, re.compile(r"\b(?:method|design|bias|confound|protocol|estimator)\b", re.IGNORECASE)),
    (GapType.DATA_COVERAGE, re.compile(r"\b(?:dataset|data coverage|sample size|sampling|missing data|annotation)\b", re.IGNORECASE)),
    (GapType.BENCHMARK_COMPARISON, re.compile(r"\b(?:benchmark|baseline|metric|comparison protocol)\b", re.IGNORECASE)),
    (GapType.TRANSLATION_IMPLEMENTATION, re.compile(r"\b(?:deployment|implementation|real-world|feasibility|translation)\b", re.IGNORECASE)),
    (GapType.CAUSAL_IDENTIFICATION, re.compile(r"\b(?:causal|mechanism|mediate|mediation|confound)\b", re.IGNORECASE)),
)


def _author_signal_gap_type(text: str) -> GapType:
    for gap_type, pattern in _AUTHOR_SIGNAL_TYPE_RULES:
        if pattern.search(text):
            return gap_type
    return GapType.AUTHOR_STATED_LIMITATION


def _author_signal_payload(gap_type: GapType, text: str, source_label: str, target_label: str, source_unit_id: str) -> dict[str, Any]:
    """Create only candidate-level payload values; contracts still enforce completeness."""
    if gap_type == GapType.MEASUREMENT_OPERATIONALIZATION:
        return {"construct": target_label, "proxy_measure": source_label, "target_measure": target_label, "validation_missing": text}
    if gap_type == GapType.CONTRADICTION_REPLICATION:
        return {"shared_claim": f"{source_label} -> {target_label}", "evidence_sets": [], "unexplained_difference": text}
    if gap_type == GapType.BOUNDARY_HETEROGENEITY:
        return {"base_relation": f"{source_label} -> {target_label}", "boundary_variable": "", "condition_a": "", "condition_b": ""}
    if gap_type == GapType.THEORY_MATHEMATICAL:
        return {"formal_claim": text, "assumptions": [], "known_validity_domain": ""}
    if gap_type == GapType.GENERALIZATION_TRANSPORTABILITY:
        return {"source_domain": source_label, "target_domain": target_label, "shift_type": "", "model_or_claim": text}
    if gap_type == GapType.METHOD_DESIGN:
        return {"current_method": source_label, "failure_mode": text, "alternative_design": "", "evaluation_criterion": ""}
    if gap_type == GapType.DATA_COVERAGE:
        return {"missing_dimension": text, "impact_on_claim": target_label, "acquisition_path": ""}
    if gap_type == GapType.BENCHMARK_COMPARISON:
        return {"comparison_target": target_label, "candidate_systems": [source_label], "common_task_missing": text, "shared_metric_missing": ""}
    if gap_type == GapType.TRANSLATION_IMPLEMENTATION:
        return {"validated_claim": f"{source_label} -> {target_label}", "deployment_context": "", "implementation_barrier": text, "feasibility_question": text}
    if gap_type == GapType.CAUSAL_IDENTIFICATION:
        return {"input": source_label, "mediator": "", "outcome": target_label, "identification_missing": text, "alternative_explanations": [], "falsification_plan": {}}
    return {"author_stated_unknown": text, "affected_claim": f"{source_label} -> {target_label}", "limitation_span_id": source_unit_id}


def _record_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in list(project.get("papergraph") or []) + list(project.get("evidence") or []):
        if not isinstance(record, dict):
            continue
        for key in ("paper_id", "doi", "openalex_id", "semantic_scholar_id"):
            identity = _clean(record.get(key))
            if identity:
                output.setdefault(identity, record)
    return output


def _signal_source_unit(signal: dict[str, Any], *, fallback_paper_id: str, fallback_branch: str) -> SourceEvidenceUnit | None:
    """Accept an explicit gap predicate only when its own source span is bound."""
    source_field = _clean(signal.get("source_field") or (signal.get("source_location") or {}).get("source_field") or (signal.get("source_location") or {}).get("section"))
    source_location = signal.get("source_location") if isinstance(signal.get("source_location"), dict) else {}
    mapping = {
        "paper_id": _clean(signal.get("paper_id")) or fallback_paper_id,
        "source_unit_id": _clean(signal.get("source_unit_id")),
        "excerpt_hash": _clean(signal.get("excerpt_hash")),
        "excerpt": _clean(signal.get("text") or signal.get("source_text")),
        "source_field": source_field,
        "source_location": source_location,
        "sub_hypothesis_id": _clean(signal.get("sub_hypothesis_id")) or fallback_branch,
        "binding_status": (
            "SOURCE_UNIT_VERIFIED"
            if _clean(signal.get("source_unit_id")) and source_field and source_field != "unresolved"
            else ""
        ),
    }
    return _source_unit_from_mapping(mapping, sub_hypothesis_id=fallback_branch)


def detect_explicit_edge_gaps(project: dict[str, Any], evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    edges = list(evidence_graph.get("edges") or [])
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if isinstance(edge, dict):
            by_paper[_clean(edge.get("paper_id"))].append(edge)
    for paper_id, record in _record_index(project).items():
        signals = record.get("gap_signals") if isinstance(record.get("gap_signals"), list) else []
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            text = _clean(signal.get("text") or signal.get("source_text"))
            predicate = _predicate_assessment(text)
            if not predicate["passes"]:
                continue
            signal_unit = _signal_source_unit(
                signal,
                fallback_paper_id=paper_id,
                fallback_branch=_clean(record.get("retrieval_branch") or record.get("sub_hypothesis_id")),
            )
            if signal_unit is None:
                diagnostics.append(
                    {
                        "stage": "GAP_PREDICATE_BINDING",
                        "reason": "GAP_PREDICATE_SOURCE_UNBOUND",
                        "paper_id": paper_id,
                        "sub_hypothesis_id": _clean(record.get("retrieval_branch") or record.get("sub_hypothesis_id")),
                        "text": text[:300],
                    }
                )
                continue
            terms = set(_content_tokens(text))
            matched_edges: list[dict[str, Any]] = []
            for edge in by_paper.get(paper_id, []):
                edge_terms = set(_content_tokens((edge.get("source") or {}).get("label"))) | set(_content_tokens((edge.get("target") or {}).get("label")))
                if terms & edge_terms:
                    matched_edges.append(edge)
            if not matched_edges:
                diagnostics.append(
                    {
                        "stage": "GAP_PREDICATE_BINDING",
                        "reason": "UNSCOPED_GAP_PREDICATE",
                        "paper_id": paper_id,
                        "sub_hypothesis_id": _clean(record.get("retrieval_branch") or record.get("sub_hypothesis_id")),
                        "text": text[:300],
                    }
                )
                continue
            for edge in matched_edges:
                source = edge["source"]
                target = edge["target"]
                branch = _clean(edge.get("sub_hypothesis_id"))
                signal_gap_type = _author_signal_gap_type(text)
                candidate = _candidate(
                        kind="MISSING_EDGE",
                        gap_type=signal_gap_type,
                        signal_type=GapSignalType.AUTHOR_STATED,
                        description=(
                            f"A source explicitly leaves the relation involving {source['label']} and {target['label']} unresolved "
                            "under its reported study conditions; the missing edge should be tested without extending the claim beyond that context."
                        ),
                        source_edges=[edge],
                        sub_hypothesis_id=branch,
                        input_label=source["label"],
                        mediator_label="",
                        outcome_label=target["label"],
                        missing_edge={"source": source["label"], "target": target["label"], "reason": "EXPLICIT_SOURCE_UNKNOWN"},
                        predicate_evidence={**predicate, "source_signal": dict(signal)},
                        gap_subtype="EXPLICIT_EDGE_UNKNOWN",
                        type_payload=_author_signal_payload(
                            signal_gap_type,
                            text,
                            source["label"],
                            target["label"],
                            signal_unit.source_unit_id,
                        ),
                    )
                existing = {
                    _clean(item.get("source_unit_id"))
                    for item in candidate.get("source_evidence_units", [])
                    if isinstance(item, dict)
                }
                if signal_unit.source_unit_id not in existing:
                    candidate["source_evidence_units"].append(signal_unit.as_dict())
                candidates.append(candidate)
    return candidates, diagnostics


def _mentions_entity(text: str, entity: AtomicEntity | None) -> bool:
    if entity is None or not entity.valid:
        return False
    entity_terms = set(_content_tokens(entity.label))
    return bool(entity_terms and entity_terms & set(_content_tokens(text)))


def detect_declared_missing_edges(project: dict[str, Any], evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind an author-stated missing M→Y edge to a declared SH contract.

    Absence from a local graph is never treated as evidence of absence in the
    literature.  This detector therefore needs all of the following: a valid
    current SH input/mediator/outcome contract, a verified A→M edge, an
    explicit source predicate naming M and Y, and an edge from that source
    paper that establishes a compatible context.  It creates no candidate for
    a merely incomplete LLM chain.
    """
    records = _record_index(project)
    edges = [edge for edge in evidence_graph.get("edges", []) if isinstance(edge, dict)]
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for branch in project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []:
        if not isinstance(branch, dict):
            continue
        branch_id = _clean(branch.get("id") or branch.get("sub_hypothesis_id"))
        axes = _declared_sh_axes(branch)
        input_axis, mediator_axis, outcome_axis = axes.get("input"), axes.get("mediator"), axes.get("outcome")
        if not branch_id or not all(axis is not None and axis.valid for axis in (input_axis, mediator_axis, outcome_axis)):
            continue
        upstream = [
            edge for edge in edges
            if _clean(edge.get("sub_hypothesis_id")) == branch_id
            and _clean((edge.get("source") or {}).get("canonical_label")) == input_axis.canonical_label
            and _clean((edge.get("target") or {}).get("canonical_label")) == mediator_axis.canonical_label
        ]
        if not upstream:
            continue
        established = any(
            _clean(edge.get("sub_hypothesis_id")) == branch_id
            and _clean((edge.get("source") or {}).get("canonical_label")) == mediator_axis.canonical_label
            and _clean((edge.get("target") or {}).get("canonical_label")) == outcome_axis.canonical_label
            for edge in edges
        )
        if established:
            continue
        for paper_id, record in records.items():
            record_branch = _clean(record.get("retrieval_branch") or record.get("sub_hypothesis_id"))
            if record_branch and record_branch != branch_id:
                continue
            for signal in record.get("gap_signals", []) if isinstance(record.get("gap_signals"), list) else []:
                if not isinstance(signal, dict):
                    continue
                text = _clean(signal.get("text") or signal.get("source_text"))
                predicate = _predicate_assessment(text)
                if not predicate["passes"] or not (_mentions_entity(text, mediator_axis) and _mentions_entity(text, outcome_axis)):
                    continue
                signal_unit = _signal_source_unit(signal, fallback_paper_id=paper_id, fallback_branch=branch_id)
                if signal_unit is None:
                    diagnostics.append(
                        {
                            "stage": "DECLARED_MISSING_EDGE_PREDICATE_BINDING",
                            "reason": "GAP_PREDICATE_SOURCE_UNBOUND",
                            "sub_hypothesis_id": branch_id,
                            "paper_id": paper_id,
                        }
                    )
                    continue
                context_edges = [
                    edge for edge in edges
                    if _clean(edge.get("paper_id")) == signal_unit.paper_id
                    and _clean(edge.get("sub_hypothesis_id")) == branch_id
                ]
                compatible_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
                for known_edge in upstream:
                    for context_edge in context_edges:
                        if assess_context_compatibility(known_edge, context_edge)["compatible"]:
                            compatible_pair = (known_edge, context_edge)
                            break
                    if compatible_pair:
                        break
                if compatible_pair is None:
                    diagnostics.append(
                        {
                            "stage": "DECLARED_MISSING_EDGE_CONTEXT_BINDING",
                            "reason": "MISSING_EDGE_PREDICATE_CONTEXT_UNMATCHED",
                            "sub_hypothesis_id": branch_id,
                            "paper_id": paper_id,
                        }
                    )
                    continue
                known_edge, context_edge = compatible_pair
                candidate = _candidate(
                    kind="MISSING_EDGE",
                    gap_type=GapType.CAUSAL_IDENTIFICATION,
                    signal_type=GapSignalType.AUTHOR_STATED,
                    description=(
                        f"The declared {mediator_axis.label} -> {outcome_axis.label} edge remains explicitly unresolved under a "
                        f"source-bound context, while {input_axis.label} -> {mediator_axis.label} has a verified local evidence edge."
                    ),
                    source_edges=[known_edge, context_edge],
                    sub_hypothesis_id=branch_id,
                    input_label=input_axis.label,
                    mediator_label=mediator_axis.label,
                    outcome_label=outcome_axis.label,
                    missing_edge={
                        "source": mediator_axis.label,
                        "target": outcome_axis.label,
                        "reason": "DECLARED_MEDIATOR_TO_OUTCOME_EDGE_EXPLICITLY_UNRESOLVED",
                    },
                    compatibility=assess_context_compatibility(known_edge, context_edge),
                    predicate_evidence={**predicate, "source_signal": dict(signal)},
                    gap_subtype="DECLARED_MISSING_EDGE",
                    type_payload={
                        "input": input_axis.label,
                        "mediator": mediator_axis.label,
                        "outcome": outcome_axis.label,
                        "identification_missing": "DECLARED_MEDIATOR_TO_OUTCOME_EDGE_EXPLICITLY_UNRESOLVED",
                        "alternative_explanations": [],
                        "falsification_plan": {},
                    },
                )
                if signal_unit.source_unit_id not in {
                    _clean(unit.get("source_unit_id"))
                    for unit in candidate["source_evidence_units"] if isinstance(unit, dict)
                }:
                    candidate["source_evidence_units"].append(signal_unit.as_dict())
                candidates.append(candidate)
    return _dedupe_candidates(candidates), diagnostics


def detect_mediation_gaps(evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edges = [edge for edge in evidence_graph.get("edges", []) if isinstance(edge, dict)]
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        incoming[_clean((edge.get("target") or {}).get("canonical_label"))].append(edge)
        outgoing[_clean((edge.get("source") or {}).get("canonical_label"))].append(edge)
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mediator_key, left_edges in incoming.items():
        for first in left_edges:
            for second in outgoing.get(mediator_key, []):
                if first.get("edge_id") == second.get("edge_id"):
                    continue
                source = first.get("source") or {}
                mediator = first.get("target") or {}
                target = second.get("target") or {}
                if _clean(source.get("canonical_label")) == _clean(target.get("canonical_label")):
                    continue
                compatibility = assess_context_compatibility(first, second)
                if not compatibility["compatible"]:
                    diagnostics.append(
                        {
                            "stage": "CROSS_PAPER_COMPATIBILITY",
                            "reason": compatibility["status"],
                            "left_edge_id": first.get("edge_id"),
                            "right_edge_id": second.get("edge_id"),
                            "sub_hypothesis_id": _clean(first.get("sub_hypothesis_id")),
                        }
                    )
                    continue
                temporal = assess_temporal_support(first, second)
                branch = _clean(first.get("sub_hypothesis_id"))
                candidate = _candidate(
                    kind="FULL_CHAIN_GAP",
                    gap_type=GapType.CAUSAL_IDENTIFICATION,
                    signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                    description=(
                        f"Evidence supports the local edges {source['label']} -> {mediator['label']} and "
                        f"{mediator['label']} -> {target['label']} in a compatible study context, but does not establish whether "
                        f"{mediator['label']} is the operative mediator of the full path."
                    ),
                    source_edges=[first, second],
                    sub_hypothesis_id=branch,
                    input_label=source["label"],
                    mediator_label=mediator["label"],
                    outcome_label=target["label"],
                    missing_edge={"source": mediator["label"], "target": target["label"], "reason": "MEDIATION_NECESSITY_OR_SUFFICIENCY_UNTESTED"},
                    compatibility={**compatibility, "temporal_support": temporal},
                    gap_subtype="MEDIATION_UNRESOLVED",
                    type_payload={
                        "input": source["label"],
                        "mediator": mediator["label"],
                        "outcome": target["label"],
                        "identification_missing": "MEDIATION_NECESSITY_OR_SUFFICIENCY_UNTESTED",
                        "alternative_explanations": ["direct_effect", "common_cause", "parallel_effect"],
                        "falsification_plan": _falsifiability_plan(
                            input_label=source["label"],
                            mediator_label=mediator["label"],
                            outcome_label=target["label"],
                            gap_class="FULL_CHAIN_GAP",
                        ),
                    },
                )
                if candidate["candidate_identity"] not in seen:
                    seen.add(candidate["candidate_identity"])
                    candidates.append(candidate)
    return candidates, diagnostics


def detect_mechanism_discrimination_gaps(evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find two source-bound, compatible mechanism paths with one endpoint pair.

    This is deliberately a graph-level *partial* gap.  The detector never
    treats two phrases as competing mechanisms: each alternative must be a
    two-edge path with verified source units and compatible context.  A source
    phrase that explicitly says the alternatives cannot be distinguished is
    retained as stronger provenance when it exists, but is not required to
    fabricate a single-paper full chain.
    """
    edges = [edge for edge in evidence_graph.get("edges", []) if isinstance(edge, dict)]
    outgoing: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[(_clean(edge.get("sub_hypothesis_id")), _clean((edge.get("source") or {}).get("canonical_label")))].append(edge)
    paths: dict[tuple[str, str, str], dict[str, tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(dict)
    diagnostics: list[dict[str, Any]] = []
    for first in edges:
        branch = _clean(first.get("sub_hypothesis_id"))
        input_key = _clean((first.get("source") or {}).get("canonical_label"))
        mediator_key = _clean((first.get("target") or {}).get("canonical_label"))
        if not branch or not input_key or not mediator_key:
            continue
        for second in outgoing.get((branch, mediator_key), []):
            outcome_key = _clean((second.get("target") or {}).get("canonical_label"))
            if not outcome_key or outcome_key == input_key:
                continue
            compatibility = assess_context_compatibility(first, second)
            if not compatibility["compatible"]:
                diagnostics.append(
                    {
                        "stage": "MECHANISM_PATH_COMPATIBILITY",
                        "reason": compatibility["status"],
                        "left_edge_id": first.get("edge_id"),
                        "right_edge_id": second.get("edge_id"),
                        "sub_hypothesis_id": branch,
                    }
                )
                continue
            paths[(branch, input_key, outcome_key)].setdefault(mediator_key, (first, second))
    candidates: list[dict[str, Any]] = []
    for (branch, _, _), by_mediator in paths.items():
        for left_key, right_key in combinations(sorted(by_mediator), 2):
            left_path = by_mediator[left_key]
            right_path = by_mediator[right_key]
            comparison_checks = [
                assess_context_compatibility(left_edge, right_edge)
                for left_edge in left_path
                for right_edge in right_path
            ]
            if not all(check["compatible"] for check in comparison_checks):
                diagnostics.append(
                    {
                        "stage": "MECHANISM_ALTERNATIVE_COMPARABILITY",
                        "reason": "CONTEXT_INCOMPATIBLE",
                        "sub_hypothesis_id": branch,
                        "alternative_mediators": [left_key, right_key],
                    }
                )
                continue
            input_label = _clean((left_path[0].get("source") or {}).get("label"))
            outcome_label = _clean((left_path[1].get("target") or {}).get("label"))
            left_label = _clean((left_path[0].get("target") or {}).get("label"))
            right_label = _clean((right_path[0].get("target") or {}).get("label"))
            excerpts = " ".join(_clean((edge.get("source_evidence") or {}).get("excerpt")) for edge in (*left_path, *right_path))
            source_assertion = bool(_COMPETING_MECHANISM_RE.search(excerpts))
            candidates.append(
                _candidate(
                    kind="MECHANISM_DISCRIMINATION",
                    gap_type=GapType.MECHANISM_COMPETITION,
                    signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                    description=(
                        f"Two source-bound and context-compatible local paths connect {input_label} to {outcome_label} through "
                        f"{left_label} and {right_label}; a discriminating intervention or joint measurement is needed to establish "
                        "which mechanism carries the endpoint response."
                    ),
                    source_edges=[*left_path, *right_path],
                    sub_hypothesis_id=branch,
                    input_label=input_label,
                    mediator_label=f"{left_label} versus {right_label}",
                    outcome_label=outcome_label,
                    missing_edge={
                        "source": input_label,
                        "target": outcome_label,
                        "reason": "COMPETING_MECHANISM_DISCRIMINATION_REQUIRED",
                        "author_stated_competition": source_assertion,
                    },
                    compatibility={
                        "compatible": True,
                        "status": "ALTERNATIVE_PATHS_CONTEXT_COMPATIBLE",
                        "comparison_count": len(comparison_checks),
                    },
                    competing_explanations=[left_label, right_label],
                    gap_subtype="COMPETING_MECHANISMS",
                    type_payload={
                        "common_input": input_label,
                        "common_outcome": outcome_label,
                        "candidate_mechanisms": [left_label, right_label],
                        "discriminating_prediction": (
                            f"Distinguish whether {left_label} or {right_label} carries the response from "
                            f"{input_label} to {outcome_label}."
                        ),
                    },
                )
            )
    return _dedupe_candidates(candidates), diagnostics


def detect_measurement_gaps(evidence_graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify source-bound proxy-to-endpoint gaps without domain keywords.

    A reported proxy or model-derived endpoint is useful evidence, but it does
    not by itself validate the mapping to the claimed observable.  This emits
    a constrained measurement gap rather than treating the proxy as a direct
    outcome measurement.
    """
    candidates: list[dict[str, Any]] = []
    for edge in evidence_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        source = edge.get("source") if isinstance(edge.get("source"), dict) else {}
        target = edge.get("target") if isinstance(edge.get("target"), dict) else {}
        excerpt = _clean((edge.get("source_evidence") or {}).get("excerpt"))
        if not _PROXY_OR_INFERENCE_RE.search(excerpt):
            continue
        candidates.append(
            _candidate(
                kind="MEASUREMENT_GAP",
                gap_type=GapType.MEASUREMENT_OPERATIONALIZATION,
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                description=(
                    f"The reported relation from {source.get('label', '')} to {target.get('label', '')} relies on a proxy, "
                    "inference, model output, or potential rather than a direct endpoint measurement; the calibration or measurement edge remains testable."
                ),
                source_edges=[edge],
                sub_hypothesis_id=_clean(edge.get("sub_hypothesis_id")),
                input_label=_clean(source.get("label")),
                mediator_label="reported proxy or inferred readout",
                outcome_label=_clean(target.get("label")),
                missing_edge={
                    "source": "reported proxy or inferred readout",
                    "target": _clean(target.get("label")),
                    "reason": "DIRECT_MEASUREMENT_OR_CALIBRATION_NOT_ESTABLISHED",
                },
                gap_subtype="PROXY_VALIDITY",
                type_payload={
                    "construct": _clean(target.get("label")),
                    "proxy_measure": _clean(source.get("label")),
                    "target_measure": _clean(target.get("label")),
                    "validation_missing": "DIRECT_MEASUREMENT_OR_CALIBRATION_NOT_ESTABLISHED",
                },
            )
        )
    return _dedupe_candidates(candidates)


def detect_conflict_and_boundary_gaps(evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in evidence_graph.get("edges", []):
        if not isinstance(edge, dict) or edge.get("polarity") == "UNSPECIFIED":
            continue
        groups[(
            _clean(edge.get("sub_hypothesis_id")),
            _clean((edge.get("source") or {}).get("canonical_label")),
            _clean((edge.get("target") or {}).get("canonical_label")),
        )].append(edge)
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for _, items in groups.items():
        for left, right in combinations(items, 2):
            if left.get("polarity") == right.get("polarity"):
                continue
            compatibility = assess_context_compatibility(left, right)
            if compatibility["compatible"]:
                kind, gap_type, reason = "CONTRADICTION_GAP", GapType.CONTRADICTION_REPLICATION, "MATCHED_CONTEXT_OPPOSITE_POLARITY"
            elif compatibility["conflicting_dimensions"]:
                kind, gap_type, reason = "BOUNDARY_GAP", GapType.BOUNDARY_HETEROGENEITY, "CONTEXT_DEPENDENT_OPPOSITE_POLARITY"
            else:
                diagnostics.append({"stage": "CONTRADICTION_COMPARABILITY", "reason": compatibility["status"], "left_edge_id": left.get("edge_id"), "right_edge_id": right.get("edge_id")})
                continue
            source = left.get("source") or {}
            target = left.get("target") or {}
            candidates.append(
                _candidate(
                    kind=kind,
                    gap_type=gap_type,
                    signal_type=GapSignalType.LITERATURE_CONTRADICTION,
                    description=(
                        f"Source-bound evidence reports opposite directions for {source.get('label', '')} -> {target.get('label', '')}. "
                        "The gap is to distinguish a reproducible contradiction from a condition-dependent boundary."
                    ),
                    source_edges=[left, right],
                    sub_hypothesis_id=_clean(left.get("sub_hypothesis_id")),
                    input_label=_clean(source.get("label")),
                    mediator_label="",
                    outcome_label=_clean(target.get("label")),
                    missing_edge={"source": _clean(source.get("label")), "target": _clean(target.get("label")), "reason": reason},
                    compatibility=compatibility,
                    gap_subtype=("OPPOSITE_POLARITY" if gap_type == GapType.CONTRADICTION_REPLICATION else "CONTEXT_DEPENDENT_EFFECT"),
                )
            )
    return candidates, diagnostics


def detect_cross_subhypothesis_translation_gaps(evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_entity_branch: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for edge in evidence_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        branch = _clean(edge.get("sub_hypothesis_id"))
        if not branch:
            continue
        for role in ("source", "target"):
            entity = edge.get(role) if isinstance(edge.get(role), dict) else {}
            if int(entity.get("specificity_score") or 0) < 2:
                continue
            key = _clean(entity.get("canonical_label"))
            if key:
                by_entity_branch[key][branch].append(edge)
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for entity_key, branches in by_entity_branch.items():
        for left_branch, right_branch in combinations(sorted(branches), 2):
            compatible_pairs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            incompatibilities: list[dict[str, Any]] = []
            for left in branches[left_branch]:
                for right in branches[right_branch]:
                    compatibility = assess_context_compatibility(left, right, cross_subhypothesis=True)
                    if compatibility["compatible"]:
                        compatible_pairs.append((left, right, compatibility))
                    else:
                        incompatibilities.append(compatibility)
            if not compatible_pairs:
                diagnostics.append(
                    {
                        "stage": "CROSS_SH_MAPPING",
                        "reason": "CROSS_SH_MAPPING_UNSUPPORTED",
                        "entity": entity_key,
                        "sub_hypothesis_ids": [left_branch, right_branch],
                        "compatibility": incompatibilities[0] if incompatibilities else {},
                    }
                )
                continue
            # One pair suffices: every retained candidate must identify exactly
            # which evidence units make the transfer question admissible.
            left, right, compatibility = compatible_pairs[0]
            entity_label = _clean((left.get("source") or {}).get("label")) if _clean((left.get("source") or {}).get("canonical_label")) == entity_key else _clean((left.get("target") or {}).get("label"))
            candidates.append(
                _candidate(
                    kind="TRANSLATION_GAP",
                    gap_type=GapType.SCALE_INTEGRATION,
                    signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                    description=(
                        f"{entity_label} is supported by source-bound edges in {left_branch} and {right_branch} under a compatible "
                        "object and system context, but the cross-sub-hypothesis transfer or coupling edge has not been established."
                    ),
                    source_edges=[left, right],
                    sub_hypothesis_id=left_branch,
                    sub_hypothesis_ids=[left_branch, right_branch],
                    input_label=_clean((left.get("source") or {}).get("label")),
                    mediator_label=entity_label,
                    outcome_label=_clean((right.get("target") or {}).get("label")),
                    missing_edge={"source": entity_label, "target": "cross-sub-hypothesis outcome", "reason": "TRANSFER_OR_COUPLING_UNESTABLISHED"},
                    compatibility=compatibility,
                    gap_subtype="CROSS_CONTEXT_COUPLING",
                    type_payload={
                        "source_scale": str(((compatibility.get("left_context") or {}).get("spatial_scale") or "")),
                        "target_scale": str(((compatibility.get("right_context") or {}).get("spatial_scale") or "")),
                        "bridge_variable": entity_label,
                        "coupling_question": "Cross-context transfer or coupling remains unestablished.",
                    },
                )
            )
    return candidates, diagnostics


def _dedupe_candidates(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = _clean(item.get("candidate_identity"))
        if key and key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _first_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return next((_clean(item) for item in value if _clean(item)), "")
    return _clean(value)


def _declared_sh_axes(branch: dict[str, Any]) -> dict[str, AtomicEntity]:
    contract = branch.get("causal_contract") if isinstance(branch.get("causal_contract"), dict) else {}
    claim_layer = contract.get("claim_layer_contract") if isinstance(contract.get("claim_layer_contract"), dict) else {}
    input_contract = contract.get("input_contract") if isinstance(contract.get("input_contract"), dict) else {}
    values = {
        "object": _clean(branch.get("scientific_object")),
        "input": _clean(branch.get("independent_variable")) or _first_text(input_contract.get("variable") or input_contract.get("input")),
        "mediator": _clean(contract.get("pivotal_mechanism")) or _first_text(contract.get("supporting_mediators")),
        "outcome": _clean(claim_layer.get("local_empirical_outcome")) or _clean(contract.get("outcome")) or _first_text(branch.get("dependent_variables")),
    }
    return {role: assess_atomic_entity(value, role=role) for role, value in values.items() if value}


def _edge_axis_overlap(edge: dict[str, Any], axes: dict[str, AtomicEntity]) -> bool:
    edge_tokens = set(_content_tokens((edge.get("source") or {}).get("label"))) | set(_content_tokens((edge.get("target") or {}).get("label")))
    return any(edge_tokens & set(_content_tokens(axis.label)) for axis in axes.values() if axis.valid)


def _branch_route_override(
    *,
    branch: dict[str, Any],
    branch_edges: list[dict[str, Any]],
    graph: dict[str, Any],
    branch_id: str,
) -> tuple[str, str, str] | None:
    """Return only source/contract diagnostic states, never a candidate.

    These states make a bad SH-to-corpus mapping visible before any generic
    ``no gap`` result is emitted.  They require an explicit SH declaration and
    cannot be triggered simply because a field was omitted.
    """
    axes = _declared_sh_axes(branch)
    declared_object = axes.get("object")
    context_objects = {
        canonical_entity_key((edge.get("context") or {}).get("research_object"))
        for edge in branch_edges
        if canonical_entity_key((edge.get("context") or {}).get("research_object"))
    }
    if declared_object and declared_object.valid and context_objects:
        object_terms = set(_content_tokens(declared_object.label))
        if object_terms and not any(object_terms & set(_content_tokens(value)) for value in context_objects):
            return (
                SH_SCOPE_OR_OBJECT_MISMATCH,
                "SH_OBJECT_TO_EVIDENCE_CONTEXT_MAPPING",
                "rebuild_retrieval_or_reextract_edges_for_the_declared_scientific_object",
            )
    required_axes = [axes.get(role) for role in ("input", "mediator", "outcome")]
    if branch_edges and all(axis is not None and axis.valid for axis in required_axes) and not any(_edge_axis_overlap(edge, axes) for edge in branch_edges):
        return (
            UNSUPPORTED_SPECULATIVE_CHAIN,
            "DECLARED_CAUSAL_CHAIN_TO_EVIDENCE_BINDING",
            "recover_source_bound_edges_for_the_declared_input_mediator_outcome_axes",
        )
    non_causal = [
        item for item in graph.get("non_causal_claims", [])
        if _clean(item.get("sub_hypothesis_id")) == branch_id
    ]
    if not branch_edges and non_causal:
        return (
            UNSUPPORTED_SPECULATIVE_CHAIN,
            "SPECULATIVE_CHAIN_SOURCE_ADMISSION",
            "replace_speculative_chain_with_source_bound_observation_or_intervention_edges",
        )
    return None


def _branch_corpus_assessment(project: dict[str, Any], branch_id: str, branch_edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Determine whether a true ``no gap`` conclusion is even admissible."""
    aggregation = project.get("papergraph_evidence_aggregation") if isinstance(project.get("papergraph_evidence_aggregation"), dict) else {}
    buckets = aggregation.get("subhypotheses") if isinstance(aggregation.get("subhypotheses"), dict) else {}
    coverage = buckets.get(branch_id) if isinstance(buckets.get(branch_id), dict) else {}
    if coverage:
        count = int(coverage.get("corpus_related_fulltext") or 0)
        target = max(1, int(coverage.get("corpus_related_fulltext_target") or 1))
        return {
            "status": "SUFFICIENT" if count >= target else "INSUFFICIENT",
            "related_fulltext_count": count,
            "related_fulltext_target": target,
            "basis": "papergraph_evidence_aggregation",
        }
    fulltext_units = {
        _clean((edge.get("source_evidence") or {}).get("source_unit_id"))
        for edge in branch_edges
        if _clean((edge.get("source_evidence") or {}).get("source_type")) == "fulltext"
        and _clean((edge.get("source_evidence") or {}).get("source_unit_id"))
    }
    return {
        "status": "UNASSESSED",
        "related_fulltext_count": len(fulltext_units),
        "related_fulltext_target": 0,
        "basis": "no_project_corpus_coverage_artifact",
    }


def _branch_diagnostics(project: dict[str, Any], graph: dict[str, Any], candidates: list[dict[str, Any]], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    branches = {
        _clean(item.get("id") or item.get("sub_hypothesis_id")): item
        for item in project.get("sub_hypotheses", []) if isinstance(item, dict) and _clean(item.get("id") or item.get("sub_hypothesis_id"))
    }
    for edge in graph.get("edges", []):
        if isinstance(edge, dict) and _clean(edge.get("sub_hypothesis_id")):
            branches.setdefault(_clean(edge.get("sub_hypothesis_id")), {})
    output: list[dict[str, Any]] = []
    for branch_id, branch in sorted(branches.items()):
        branch_edges = [edge for edge in graph.get("edges", []) if _clean(edge.get("sub_hypothesis_id")) == branch_id]
        branch_rejected = [item for item in graph.get("rejected_edges", []) if _clean(item.get("sub_hypothesis_id")) == branch_id]
        branch_candidates = [item for item in candidates if branch_id in list(item.get("sub_hypothesis_ids") or [])]
        branch_diagnostics = [item for item in diagnostics if branch_id in list(item.get("sub_hypothesis_ids") or []) or _clean(item.get("sub_hypothesis_id")) == branch_id]
        corpus = _branch_corpus_assessment(project, branch_id, branch_edges)
        retrieval_execution = (
            branch.get("research_question_retrieval_execution")
            if isinstance(branch.get("research_question_retrieval_execution"), dict)
            else {}
        )
        slot_coverage_ledger = (
            retrieval_execution.get("slot_coverage_ledger")
            if isinstance(retrieval_execution.get("slot_coverage_ledger"), dict)
            else {}
        )
        slot_shortages = {
            str(slot): dict(item)
            for slot, item in slot_coverage_ledger.items()
            if isinstance(item, dict)
            and str(item.get("claim_readiness") or "") != "READY"
        }
        slot_shortfall_codes = {
            _clean(code)
            for entry in slot_shortages.values()
            if isinstance(entry, dict)
            for code in entry.get("shortfall_reason_codes", [])
            if _clean(code)
        }
        override = _branch_route_override(branch=branch, branch_edges=branch_edges, graph=graph, branch_id=branch_id)
        if slot_shortages and not branch_candidates:
            state = INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS
            first_blocking_stage = (
                "SLOT_DIVERSITY_OR_COHERENCE"
                if slot_shortfall_codes & {
                    "EVIDENCE_DIVERSITY_SHORTAGE",
                    "COMPARABILITY_COHERENCE_SHORTAGE",
                }
                else "SLOT_EVIDENCE_ADMISSION"
            )
            next_action = (
                "run_independent_confirmation_or_coherence_retrieval_for_underqualified_slots"
                if slot_shortfall_codes & {
                    "EVIDENCE_DIVERSITY_SHORTAGE",
                    "COMPARABILITY_COHERENCE_SHORTAGE",
                }
                else "run_slot_directed_retrieval_for_missing_source_bound_requirements"
            )
        elif override and not branch_candidates:
            state, first_blocking_stage, next_action = override
        elif branch_candidates:
            state = GAP_CANDIDATES_DISCOVERED
            first_blocking_stage = ""
            next_action = "run_type_specific_semantic_audit_before_retrieval_or_hypothesis_selection"
        elif not branch_edges:
            state = INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS
            first_blocking_stage = "ATOMIC_EDGE_EXTRACTION" if branch_rejected else "SOURCE_EVIDENCE_INGESTION"
            next_action = "recover_source_bound_atomic_edges"
        elif branch_rejected:
            state = GAP_NOT_RECOVERED_FROM_EVIDENCE
            first_blocking_stage = "ATOMIC_EDGE_EXTRACTION"
            next_action = "repair_relation_clause_or_low_information_entity_extraction"
        elif branch_diagnostics:
            state = GAP_NOT_RECOVERED_FROM_EVIDENCE
            first_blocking_stage = _clean(branch_diagnostics[0].get("stage")) or "EDGE_TO_GAP_BINDING"
            next_action = "resolve_source_role_or_context_compatibility"
        elif corpus["status"] != "SUFFICIENT":
            state = INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS
            first_blocking_stage = "CORPUS_SUFFICIENCY_ASSESSMENT"
            next_action = "establish_or_refresh_related_fulltext_coverage_before_no_gap_conclusion"
        else:
            state = NO_EVIDENCE_OF_GAP_IN_SUFFICIENT_CORPUS
            first_blocking_stage = ""
            next_action = "no_gap_claim_without_new_source_bound_unknown_or_conflict"
        output.append(
            {
                "sub_hypothesis_id": branch_id,
                "focus": _clean(branch.get("focus") or branch.get("hypothesis")),
                "state": state,
                "atomic_edge_count": len(branch_edges),
                "rejected_edge_count": len(branch_rejected),
                "candidate_count": len(branch_candidates),
                "corpus_status": corpus["status"],
                "related_fulltext_count": corpus["related_fulltext_count"],
                "related_fulltext_target": corpus["related_fulltext_target"],
                "corpus_assessment_basis": corpus["basis"],
                "slot_coverage_ledger": slot_coverage_ledger,
                "slot_coverage_shortages": slot_shortages,
                "slot_shortfall_reason_codes": sorted(slot_shortfall_codes),
                "declared_axes": {role: entity.as_dict() for role, entity in _declared_sh_axes(branch).items()},
                "first_blocking_stage": first_blocking_stage,
                "next_action": next_action,
            }
        )
    return output


def _v2_source_unit(
    assertion: dict[str, Any],
    *,
    source_spans_by_id: dict[str, dict[str, Any]] | None = None,
    runtime_source_spans_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Project an assertion's immutable span with optional runtime text.

    ``source_spans_by_id`` is the quote-free graph projection.  Runtime spans
    are provided only by the current narrow TanXi evidence view, keyed by the
    same immutable span ID.  A mismatch is rejected instead of silently
    attaching text from another document version.
    """
    span: dict[str, Any] = {}
    for source_span_id in assertion.get("source_span_ids", []):
        candidate = (source_spans_by_id or {}).get(_clean(source_span_id))
        if isinstance(candidate, dict):
            span = candidate
            break
    if not span:
        return None
    source_span_id = _clean(span.get("source_span_id") or span.get("source_unit_id"))
    runtime_span = (
        (runtime_source_spans_by_id or {}).get(source_span_id)
        if source_span_id
        else None
    )
    if isinstance(runtime_span, dict):
        expected_paper_id = _clean(span.get("paper_id") or assertion.get("paper_id"))
        expected_version = _clean(
            span.get("document_version_hash") or assertion.get("document_version_hash")
        )
        expected_quote_hash = _clean(span.get("quote_hash") or span.get("excerpt_hash"))
        runtime_quote_hash = _clean(
            runtime_span.get("quote_hash") or runtime_span.get("excerpt_hash")
        )
        if (
            _clean(runtime_span.get("paper_id")) != expected_paper_id
            or _clean(runtime_span.get("document_version_hash")) != expected_version
            or (expected_quote_hash and runtime_quote_hash != expected_quote_hash)
        ):
            return None
        span = {**span, **runtime_span}
    scope = assertion.get("scope_tuple") if isinstance(assertion.get("scope_tuple"), dict) else {}
    return {
        "paper_id": _clean(span.get("paper_id")),
        "document_version_hash": _clean(span.get("document_version_hash")),
        "source_unit_id": _clean(span.get("source_unit_id") or span.get("source_span_id")),
        "source_span_id": _clean(span.get("source_span_id")),
        "excerpt_hash": _clean(span.get("excerpt_hash") or span.get("quote_hash")),
        "excerpt": _clean(span.get("quote") or span.get("excerpt")),
        "binding_status": _clean(span.get("binding_status")) or "SOURCE_UNIT_VERIFIED",
        "source_field": _clean(span.get("source_field") or span.get("section")),
        "section": _clean(span.get("section")),
        "source_locator": _clean(span.get("source_locator")),
        "source_type": _clean(span.get("source_type")) or "fulltext",
        "conditions": {str(key): _clean(value) for key, value in scope.items() if _clean(value)},
        "evidence_assertion_id": _clean(assertion.get("assertion_id")),
        # ``assertion_id`` is the public, cross-artifact field.  Keep the
        # older explicit spelling in the source unit for local readability,
        # but never force downstream V3 consumers to reconstruct it.
        "assertion_id": _clean(assertion.get("assertion_id")),
        "research_question_contract_id": _clean(assertion.get("research_question_contract_id")),
        "assertion_kinds": list(assertion.get("assertion_kinds") or []),
        "textual_explicitness": "EXPLICIT",
        "epistemic_basis": _clean(assertion.get("epistemic_basis")),
        "attribution": _clean(assertion.get("attribution")),
        "proposition_id": _clean(assertion.get("proposition_id")),
        "section_id": _clean(span.get("section_id")),
        "section_type": _clean(span.get("section_type")),
        "document_char_start": span.get("char_start"),
        "document_char_end": span.get("char_end"),
        "quote_char_start": assertion.get("quote_char_start"),
        "quote_char_end": assertion.get("quote_char_end"),
        "exact_quote": _clean(assertion.get("exact_quote") or span.get("quote") or span.get("excerpt")),
        "slot_support_ids": sorted({
            _clean(item.get("slot_support_id"))
            for item in assertion.get("slot_support", [])
            if isinstance(item, dict) and _clean(item.get("slot_support_id"))
        }),
    }


def _v2_payload(
    gap_type: GapType,
    assertion: dict[str, Any],
    contract: dict[str, Any],
    *,
    source_unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed only fields whose values are either declared or source quoted.

    Empty fields are intentional: later semantic and retrieval qualification
    sees them as missing evidence, rather than accepting a guessed value.
    """
    quote = _clean((source_unit or {}).get("excerpt") or assertion.get("quote"))
    scope = assertion.get("scope_tuple") if isinstance(assertion.get("scope_tuple"), dict) else {}
    target = contract.get("claim_target") if isinstance(contract.get("claim_target"), dict) else {}
    construct = _clean(target.get("target_construct") or scope.get("research_object"))
    relation = _clean(target.get("target_relation"))
    span_id = _clean(
        (source_unit or {}).get("source_span_id")
        or next(iter(assertion.get("source_span_ids") or []), "")
    )
    if gap_type == GapType.EMPIRICAL_COVERAGE:
        return {
            "phenomenon": quote,
            "target_object": construct,
            "target_condition": _clean(scope.get("condition_or_regime")),
            "available_direct_evidence_count": 1,
            "coverage_dimension_missing": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
        }
    if gap_type == GapType.AUTHOR_STATED_LIMITATION:
        return {
            "limitation_kind": "AUTHOR_STATED_UNKNOWN",
            "author_stated_unknown": quote,
            "affected_claim": relation or construct,
            "scope_of_limitation": _clean(scope.get("condition_or_regime") or scope.get("research_object")),
            "limitation_span_id": span_id,
        }
    if gap_type == GapType.CAUSAL_IDENTIFICATION:
        return {
            "input": _clean(scope.get("intervention_or_exposure")),
            "outcome": _clean(scope.get("outcome_definition")),
            "identification_missing": quote,
            "alternative_explanations": [],
            "identification_design": {},
        }
    if gap_type == GapType.MECHANISM_COMPETITION:
        return {
            "common_input": _clean(scope.get("intervention_or_exposure")),
            "common_outcome": _clean(scope.get("outcome_definition")),
            "candidate_mechanisms": [],
            "discriminating_prediction": quote if "distinguish" in quote.lower() else "",
        }
    if gap_type == GapType.BOUNDARY_HETEROGENEITY:
        return {
            "base_relation": relation or quote,
            "boundary_variable": _clean(scope.get("condition_or_regime")),
            "condition_a": _clean(scope.get("condition_or_regime")),
            "condition_b": "",
            "effect_difference": "",
            "threshold_unknown": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
        }
    if gap_type == GapType.CONTRADICTION_REPLICATION:
        return {
            "shared_claim": relation or construct,
            "evidence_sets": [],
            "comparability_verdict": "UNASSESSED",
            "unexplained_difference": quote,
        }
    if gap_type == GapType.MEASUREMENT_OPERATIONALIZATION:
        return {
            "construct": construct,
            "proxy_measure": quote if "MEASUREMENT_DEFINITION" in assertion.get("assertion_kinds", []) else "",
            "target_measure": _clean(scope.get("measurement_definition")),
            "mapping_status": "UNVALIDATED" if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "UNASSESSED",
            "validation_missing": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
        }
    if gap_type == GapType.THEORY_MATHEMATICAL:
        return {
            "formal_claim": quote if "FORMAL_PROPOSITION" in assertion.get("assertion_kinds", []) else "",
            "assumptions": [quote] if "FORMAL_ASSUMPTION" in assertion.get("assertion_kinds", []) else [],
            "known_validity_domain": _clean(scope.get("condition_or_regime")),
            "counterexample_status": "UNRESOLVED" if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "UNASSESSED",
        }
    if gap_type == GapType.GENERALIZATION_TRANSPORTABILITY:
        return {
            "source_domain": _clean(scope.get("population_or_system") or scope.get("dataset_or_corpus")),
            "target_domain": "",
            "shift_type": quote if "shift" in quote.lower() or "generaliz" in quote.lower() else "",
            "model_or_claim": relation or construct,
            "external_validation_status": "UNASSESSED",
        }
    if gap_type == GapType.METHOD_DESIGN:
        return {
            "current_method": quote if "METHOD_DESCRIPTION" in assertion.get("assertion_kinds", []) else _clean(scope.get("method_or_design")),
            "failure_mode": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
            "bias_or_identification_problem": "",
            "alternative_design": "",
            "evaluation_criterion": "",
        }
    if gap_type == GapType.DATA_COVERAGE:
        return {
            "missing_variables": [quote] if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else [],
            "missing_population_or_system": "",
            "missing_regime": _clean(scope.get("condition_or_regime")),
            "missing_time_horizon": _clean(scope.get("time_window")),
            "impact_on_claim": quote,
            "acquisition_path": "",
        }
    if gap_type == GapType.SCALE_INTEGRATION:
        return {
            "source_scale": _clean(scope.get("spatial_scale")),
            "target_scale": _clean(scope.get("temporal_scale")),
            "bridge_variable": "",
            "coupling_question": quote,
        }
    if gap_type == GapType.BENCHMARK_COMPARISON:
        return {
            "comparison_target": construct,
            "candidate_systems": [],
            "common_task_missing": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
            "shared_metric_missing": "",
            "protocol_missing": "",
        }
    return {
        "validated_claim": relation or construct,
        "deployment_context": _clean(scope.get("population_or_system") or scope.get("condition_or_regime")),
        "implementation_barrier": quote if "AUTHOR_LIMITATION" in assertion.get("assertion_kinds", []) else "",
        "feasibility_question": quote,
    }


def _v2_candidate(
    project: dict[str, Any],
    *,
    gap_type: GapType,
    assertion: dict[str, Any],
    contract: dict[str, Any],
    signal_type: GapSignalType,
    description: str,
    source_spans_by_id: dict[str, dict[str, Any]] | None = None,
    runtime_source_spans_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    unit = _v2_source_unit(
        assertion,
        source_spans_by_id=source_spans_by_id,
        runtime_source_spans_by_id=runtime_source_spans_by_id,
    )
    if not isinstance(unit, dict) or not _clean(unit.get("source_unit_id")):
        return None
    material = "|".join((gap_type.value, _clean(contract.get("contract_id")), _clean(assertion.get("assertion_id")), _clean(unit.get("source_unit_id"))))
    identity = "gapv2_" + sha256(material.encode("utf-8")).hexdigest()[:22]
    assessment = initial_gap_assessment(
        gap_type=gap_type,
        signal_type=signal_type,
        candidate_stage=CandidateStage.RAW_CANDIDATE,
    )
    candidate = {
        "schema_version": "gap_candidate_v2",
        "gap_id": identity,
        "candidate_identity": identity,
        "project_id": _clean(project.get("project_id")),
        "description": description,
        "sub_hypothesis_ids": [_clean(contract.get("sub_hypothesis_id"))] if _clean(contract.get("sub_hypothesis_id")) else [],
        "research_question": dict(contract.get("research_question") or {}),
        "research_question_contract": contract,
        "source_evidence_units": [unit],
        "source_assertion_ids": [_clean(assertion.get("assertion_id"))],
        "assertion_ids": [_clean(assertion.get("assertion_id"))],
        "slot_support_ids": sorted({
            _clean(item.get("slot_support_id"))
            for item in assertion.get("slot_support", [])
            if isinstance(item, dict) and _clean(item.get("slot_support_id"))
        }),
        "type_payload": _v2_payload(
            gap_type,
            assertion,
            contract,
            source_unit=unit,
        ),
        "gap_assessment": assessment,
        "evidence_graph_contract": {
            "schema_version": "heterogeneous_evidence_graph_binding_v2",
            "assertion_ids": [_clean(assertion.get("assertion_id"))],
            "source_span_ids": [_clean(unit.get("source_span_id"))],
            "document_version_hashes": [_clean(unit.get("document_version_hash"))],
            "research_question_contract_id": _clean(contract.get("contract_id")),
            "research_question_contract_revision": _clean(contract.get("contract_revision") or contract.get("declaration_hash")),
            "textual_explicitness": "EXPLICIT",
        },
    }
    return synchronize_candidate_surface(candidate, assessment)


def detect_typed_assertion_gaps(project: dict[str, Any], evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover v2 candidates only from explicit assertions or bounded inferences.

    An SH's expected gap type is a retrieval prior, never a gap verdict.  A
    candidate is emitted only when text contains an explicit limitation or a
    type-relevant source assertion; route qualification remains downstream.
    """
    contracts = {
        _clean(item.get("sub_hypothesis_id")): item
        for item in (
            branch.get("research_question_contract")
            for branch in project.get("sub_hypotheses", []) if isinstance(branch, dict)
        )
        if isinstance(item, dict)
    }
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    source_spans_by_id = {
        _clean(item.get("source_span_id") or item.get("source_unit_id")): item
        for item in evidence_graph.get("source_spans", [])
        if isinstance(item, dict)
        and _clean(item.get("source_span_id") or item.get("source_unit_id"))
    }
    runtime_source_spans_by_id = (
        project.get("_tanxi_runtime_source_spans_by_id")
        if isinstance(project.get("_tanxi_runtime_source_spans_by_id"), dict)
        else {}
    )
    for assertion in evidence_graph.get("assertions", []):
        if not isinstance(assertion, dict):
            continue
        branch_id = _clean(assertion.get("sub_hypothesis_id"))
        contract = contracts.get(branch_id)
        if not contract:
            diagnostics.append({"stage": "RESEARCH_QUESTION_CONTRACT", "reason": "ASSERTION_WITHOUT_V2_SH_CONTRACT", "assertion_id": _clean(assertion.get("assertion_id")), "sub_hypothesis_id": branch_id})
            continue
        kinds = {str(item) for item in assertion.get("assertion_kinds", [])}
        expected = [GapType(item) for item in (contract.get("research_question") or {}).get("expected_gap_type_priors", []) if item in {value.value for value in GapType}]
        if "AUTHOR_LIMITATION" in kinds:
            candidate = _v2_candidate(
                project,
                gap_type=GapType.AUTHOR_STATED_LIMITATION,
                assertion=assertion,
                contract=contract,
                signal_type=GapSignalType.AUTHOR_STATED,
                description="A bounded source span explicitly states an unresolved item; its scope and scientific significance require type-specific audit.",
                source_spans_by_id=source_spans_by_id,
                runtime_source_spans_by_id=runtime_source_spans_by_id,
            )
            if isinstance(candidate, dict):
                candidates.append(candidate)
            else:
                diagnostics.append({
                    "stage": "ASSERTION_TO_GAP_SIGNAL",
                    "reason": "SOURCE_SPAN_ARTIFACT_MISSING_FOR_ASSERTION",
                    "assertion_id": _clean(assertion.get("assertion_id")),
                    "source_span_ids": list(assertion.get("source_span_ids") or []),
                })
        for gap_type in expected:
            type_relevant = {
                GapType.MEASUREMENT_OPERATIONALIZATION: "MEASUREMENT_DEFINITION" in kinds,
                GapType.THEORY_MATHEMATICAL: bool({"FORMAL_PROPOSITION", "FORMAL_ASSUMPTION"} & kinds),
                GapType.METHOD_DESIGN: "METHOD_DESCRIPTION" in kinds,
                GapType.DATA_COVERAGE: "DATASET_COVERAGE" in kinds,
                GapType.SCALE_INTEGRATION: "SCALE_STATEMENT" in kinds,
                GapType.BENCHMARK_COMPARISON: "BENCHMARK_RESULT" in kinds,
                GapType.TRANSLATION_IMPLEMENTATION: "IMPLEMENTATION_CONSTRAINT" in kinds,
                GapType.BOUNDARY_HETEROGENEITY: "SCOPE_CONDITION" in kinds,
                GapType.CONTRADICTION_REPLICATION: "REPLICATION_RESULT" in kinds,
                GapType.CAUSAL_IDENTIFICATION: "CAUSAL_CLAIM" in kinds,
                GapType.MECHANISM_COMPETITION: "CAUSAL_CLAIM" in kinds,
                GapType.GENERALIZATION_TRANSPORTABILITY: "SCOPE_CONDITION" in kinds or "EMPIRICAL_RESULT" in kinds,
                GapType.EMPIRICAL_COVERAGE: "EMPIRICAL_RESULT" in kinds,
                GapType.AUTHOR_STATED_LIMITATION: False,
            }.get(gap_type, False)
            if not ("AUTHOR_LIMITATION" in kinds or type_relevant):
                continue
            candidate = _v2_candidate(
                project,
                gap_type=gap_type,
                assertion=assertion,
                contract=contract,
                signal_type=GapSignalType.AUTHOR_STATED if "AUTHOR_LIMITATION" in kinds else GapSignalType.INFERRED_FROM_EVIDENCE,
                description="A source-bound explicit assertion matches the SH evidence contract and is retained as a diagnostic candidate pending semantic and retrieval qualification.",
                source_spans_by_id=source_spans_by_id,
                runtime_source_spans_by_id=runtime_source_spans_by_id,
            )
            if isinstance(candidate, dict):
                candidates.append(candidate)
            else:
                diagnostics.append({
                    "stage": "ASSERTION_TO_GAP_SIGNAL",
                    "reason": "SOURCE_SPAN_ARTIFACT_MISSING_FOR_ASSERTION",
                    "assertion_id": _clean(assertion.get("assertion_id")),
                    "source_span_ids": list(assertion.get("source_span_ids") or []),
                })
    # Derived inferences are retained in the graph solely as auditable
    # retrieval leads.  They cannot materialise a v2 scientific candidate,
    # because their source ceiling explicitly excludes validation and primary
    # admission.  Surface a diagnostic so orchestration can schedule the
    # appropriate targeted search without smuggling the inference into a gap.
    for inference in evidence_graph.get("derived_inferences", []):
        if not isinstance(inference, dict):
            continue
        if inference.get("route_ceiling") not in {"TARGETED_RETRIEVAL", "DIAGNOSTIC"}:
            diagnostics.append({"stage": "DERIVED_INFERENCE", "reason": "INVALID_ROUTE_CEILING", "inference_id": _clean(inference.get("inference_id"))})
        else:
            diagnostics.append({
                "stage": "DERIVED_INFERENCE",
                "reason": "DERIVED_INFERENCE_REQUIRES_NEW_SOURCE_BOUND_RETRIEVAL",
                "inference_id": _clean(inference.get("inference_id")),
                "route_ceiling": _clean(inference.get("route_ceiling")),
                "input_assertion_ids": list(inference.get("input_assertion_ids") or []),
            })
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = _clean(candidate.get("candidate_identity"))
        if identity and identity not in seen:
            seen.add(identity)
            deduped.append(candidate)
    return deduped, diagnostics


def _v3_branch_diagnostics(
    project: dict[str, Any],
    graph: dict[str, Any],
    candidates: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    assertions = [item for item in graph.get("assertions", []) if isinstance(item, dict)]
    projection_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    execution_ledger = (
        project.get("research_question_retrieval_executions_v3")
        if isinstance(project.get("research_question_retrieval_executions_v3"), dict)
        else {}
    )
    for index, branch in enumerate(project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []):
        if not isinstance(branch, dict):
            continue
        branch_id = _clean(branch.get("id") or branch.get("sub_hypothesis_id") or f"SH{index + 1}")
        contract = branch.get("research_question_contract") if isinstance(branch.get("research_question_contract"), dict) else {}
        contract_id = _clean(contract.get("contract_id"))
        execution = execution_ledger.get(branch_id)
        execution = execution if isinstance(execution, dict) else {}
        slot_coverage_ledger = (
            execution.get("slot_coverage_ledger")
            if isinstance(execution.get("slot_coverage_ledger"), dict)
            else {}
        )
        slot_shortages = {
            str(slot): dict(entry)
            for slot, entry in slot_coverage_ledger.items()
            if isinstance(entry, dict)
            and str(entry.get("claim_readiness") or "") != "READY"
        }
        slot_shortfall_codes = {
            _clean(code)
            for entry in slot_shortages.values()
            if isinstance(entry, dict)
            for code in entry.get("shortfall_reason_codes", [])
            if _clean(code)
        }
        slot_quality_summary = {
            str(slot): {
                "distinct_assertion_count": int(entry.get("distinct_assertion_count") or 0),
                "distinct_span_count": int(entry.get("distinct_span_count") or 0),
                "distinct_paper_count": int(entry.get("distinct_paper_count") or 0),
                "coverage_bundle_id": _clean(entry.get("coverage_bundle_id")),
                "coverage_bundle_kind": _clean(entry.get("coverage_bundle_kind")),
                "comparison_signature": _clean(entry.get("comparison_signature")),
                "claim_readiness": _clean(entry.get("claim_readiness")),
                "provider_dispatch_status": _clean(entry.get("provider_dispatch_status")),
            }
            for slot, entry in slot_coverage_ledger.items()
            if isinstance(entry, dict)
        }
        single_source_dependency_slots = sorted(
            slot
            for slot, entry in slot_coverage_ledger.items()
            if isinstance(entry, dict)
            and int(entry.get("distinct_paper_count") or 0) == 1
            and bool((entry.get("policy") or {}).get("require_independent_confirmation"))
        )
        branch_assertions = [item for item in assertions if _clean(item.get("sub_hypothesis_id")) == branch_id]
        branch_candidates = [item for item in candidates if branch_id in list(item.get("sub_hypothesis_ids") or [])]
        recovery = classify_evidence_recovery(
            project,
            {
                "sub_hypothesis_id": branch_id,
                "research_question_contract_id": contract_id,
                "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
            },
            diagnostics=diagnostics,
        )
        if not contract:
            state, stage, action = "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "RESEARCH_QUESTION_CONTRACT", "rebuild_subhypothesis_as_research_question_contract_v3"
        elif recovery.get("failure_type") not in {"NO_RECOVERY_REQUIRED", "GENUINE_SLOT_SHORTAGE"}:
            state, stage, action = (
                INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS,
                _clean(recovery.get("failure_type")),
                _clean(recovery.get("next_action")),
            )
        elif slot_shortages:
            state, stage, action = (
                INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS,
                "SLOT_DIVERSITY_OR_COHERENCE"
                if slot_shortfall_codes & {
                    "EVIDENCE_DIVERSITY_SHORTAGE",
                    "COMPARABILITY_COHERENCE_SHORTAGE",
                }
                else "SLOT_EVIDENCE_ADMISSION",
                "run_independent_confirmation_or_coherence_retrieval_for_underqualified_slots"
                if slot_shortfall_codes & {
                    "EVIDENCE_DIVERSITY_SHORTAGE",
                    "COMPARABILITY_COHERENCE_SHORTAGE",
                }
                else "run_slot_directed_retrieval_for_missing_source_bound_requirements",
            )
        elif not branch_assertions:
            state, stage, action = INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS, "EXPLICIT_ASSERTION_EXTRACTION", "retrieve_or_import_fulltext_and_extract_source_spans"
        elif branch_candidates:
            state, stage, action = GAP_CANDIDATES_DISCOVERED, "", "run_type_specific_semantic_audit_before_retrieval_or_package_selection"
        else:
            state, stage, action = GAP_NOT_RECOVERED_FROM_EVIDENCE, "ASSERTION_TO_GAP_SIGNAL", "run_type_directed_retrieval_without_promoting_corpus_absence_to_a_gap"
        output.append({
            "sub_hypothesis_id": branch_id,
            "research_question_contract_id": contract_id,
            "focus": _clean(branch.get("focus") or (contract.get("research_question") or {}).get("question_text")),
            "state": state,
            "explicit_assertion_count": len(branch_assertions),
            "current_contract_admitted_assertion_count": int(
                (projection_summary.get("detector_admitted_assertion_count_by_contract") or {}).get(contract_id)
                or len(branch_assertions)
            ),
            "background_assertion_count": int(
                (projection_summary.get("background_assertion_count_by_contract") or {}).get(contract_id)
                or 0
            ),
            "retrieval_execution_status": _clean(execution.get("retrieval_execution_status") or execution.get("status")),
            "required_direct_slot_ids": list(execution.get("required_direct_slot_ids") or []),
            "covered_direct_slot_ids": list(execution.get("covered_direct_slot_ids") or []),
            "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
            "typed_slot_admitted_source_count": int(execution.get("direct_evidence_paper_count") or 0),
            "slot_coverage_ledger": slot_coverage_ledger,
            "slot_coverage_shortages": slot_shortages,
            "slot_shortfall_reason_codes": sorted(slot_shortfall_codes),
            "slot_quality_summary": slot_quality_summary,
            "single_source_dependency_slots": single_source_dependency_slots,
            "candidate_count": len(branch_candidates),
            "first_blocking_stage": stage,
            "next_action": action,
            "recovery_classification": recovery,
            "recovery_failure_type": _clean(recovery.get("failure_type")),
            "slot_directed_retrieval_allowed": recovery.get("slot_directed_retrieval_allowed") is True,
            "research_question_kind": _clean((contract.get("research_question") or {}).get("question_kind")),
            "research_question_contract_revision": _clean(
                contract.get("contract_revision") or contract.get("declaration_hash")
            ),
        })
    return output


def _candidate_payload_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (str, bytes)):
        return bool(_clean(value))
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(_clean(value))


def _candidate_identity_material(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _normalized_context_source_units(
    context: DetectionContext,
    assertion_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return only exact assertion/span bindings contained in one context."""

    assertions_by_id = {
        _clean(item.get("assertion_id")): item
        for item in context.assertions
        if isinstance(item, dict) and _clean(item.get("assertion_id"))
    }
    units: list[dict[str, Any]] = []
    seen_span_ids: set[str] = set()
    for assertion_id in assertion_ids:
        assertion = assertions_by_id.get(assertion_id)
        if not isinstance(assertion, dict):
            raise ValueError("GAP_CANDIDATE_ASSERTION_NOT_IN_DETECTION_CONTEXT")
        source_units = context.source_units_by_assertion.get(assertion_id)
        if not isinstance(source_units, list) or not source_units:
            raise ValueError("GAP_CANDIDATE_ASSERTION_HAS_NO_BOUND_SOURCE_UNIT")
        for raw_unit in source_units:
            if not isinstance(raw_unit, dict):
                continue
            source_span_id = _clean(
                raw_unit.get("source_span_id")
                or raw_unit.get("source_unit_id")
                or raw_unit.get("node_id")
            )
            if not source_span_id or source_span_id in seen_span_ids:
                continue
            assertion_version = _clean(assertion.get("document_version_hash"))
            source_version = _clean(raw_unit.get("document_version_hash"))
            if assertion_version and source_version and assertion_version != source_version:
                raise ValueError("GAP_CANDIDATE_SOURCE_UNIT_DOCUMENT_VERSION_MISMATCH")
            seen_span_ids.add(source_span_id)
            scope = assertion.get("scope_tuple") if isinstance(assertion.get("scope_tuple"), dict) else {}
            units.append(
                {
                    "paper_id": _clean(raw_unit.get("paper_id") or assertion.get("paper_id")),
                    "document_version_hash": source_version or assertion_version,
                    "source_unit_id": _clean(raw_unit.get("source_unit_id") or source_span_id),
                    "source_span_id": source_span_id,
                    "excerpt_hash": _clean(raw_unit.get("excerpt_hash") or raw_unit.get("quote_hash")),
                    "binding_status": _clean(raw_unit.get("binding_status")) or "SOURCE_UNIT_VERIFIED",
                    "source_field": _clean(raw_unit.get("source_field") or raw_unit.get("section")),
                    "section": _clean(raw_unit.get("section")),
                    "source_locator": _clean(raw_unit.get("source_locator")),
                    "source_type": _clean(raw_unit.get("source_type")),
                    "conditions": {
                        str(key): _clean(value)
                        for key, value in scope.items()
                        if _clean(value)
                    },
                    "assertion_id": assertion_id,
                    "evidence_assertion_id": assertion_id,
                    "research_question_contract_id": _clean(
                        assertion.get("research_question_contract_id")
                    ),
                    "assertion_kinds": list(assertion.get("assertion_kinds") or []),
                    "textual_explicitness": _clean(assertion.get("textual_explicitness")) or "EXPLICIT",
                    "epistemic_basis": _clean(assertion.get("epistemic_basis")),
                    "attribution": _clean(assertion.get("attribution")),
                    "proposition_id": _clean(assertion.get("proposition_id")),
                    "section_id": _clean(raw_unit.get("section_id")),
                    "section_type": _clean(raw_unit.get("section_type")),
                    "document_char_start": raw_unit.get("char_start"),
                    "document_char_end": raw_unit.get("char_end"),
                    "quote_char_start": assertion.get("quote_char_start"),
                    "quote_char_end": assertion.get("quote_char_end"),
                    "exact_quote": _clean(
                        assertion.get("exact_quote")
                        or raw_unit.get("quote")
                        or raw_unit.get("excerpt")
                    ),
                    "slot_support_ids": sorted({
                        _clean(item.get("slot_support_id"))
                        for item in assertion.get("slot_support", [])
                        if isinstance(item, dict) and _clean(item.get("slot_support_id"))
                    }),
                }
            )
    if not units:
        raise ValueError("GAP_CANDIDATE_HAS_NO_BOUND_SOURCE_UNITS")
    return units, assertions_by_id


def create_source_bound_gap_candidate(
    *,
    context: DetectionContext,
    gap_type: GapType | str,
    gap_subtype: str = "",
    signal_type: GapSignalType | str,
    assertion_ids: list[str] | tuple[str, ...],
    type_payload: dict[str, Any],
    detection_witness: dict[str, Any],
    description: str,
    detector_id: str,
    detector_policy_version: str,
) -> dict[str, Any]:
    """Create one multi-source candidate from an already bounded V3 context.

    This is the only factory used by the new detector path.  It never reads
    a project-level causal graph, historical candidate fields, or a global
    assertion projection.  Every source unit is rechecked against the exact
    DetectionContext that supplied the structural witness.
    """

    current_context = _validated_detection_context_for_runtime(context)
    normalized_type = GapType(str(getattr(gap_type, "value", gap_type)))
    contract = contract_for(normalized_type)
    normalized_subtype = normalize_gap_subtype(normalized_type, gap_subtype)
    normalized_signal = GapSignalType(str(getattr(signal_type, "value", signal_type)))
    if normalized_signal not in contract.discovery_spec.allowed_signal_types:
        raise ValueError("GAP_CANDIDATE_SIGNAL_TYPE_NOT_ALLOWED_BY_DISCOVERY_CONTRACT")
    canonical_assertion_ids = sorted({_clean(item) for item in assertion_ids if _clean(item)})
    if not canonical_assertion_ids:
        raise ValueError("GAP_CANDIDATE_REQUIRES_SOURCE_ASSERTION_IDS")
    units, assertions_by_id = _normalized_context_source_units(current_context, canonical_assertion_ids)
    paper_ids = sorted({_clean(item.get("paper_id")) for item in units if _clean(item.get("paper_id"))})
    if len(units) < contract.discovery_spec.minimum_source_units:
        raise ValueError("GAP_CANDIDATE_DISCOVERY_MINIMUM_SOURCE_UNITS_UNSATISFIED")
    if len(paper_ids) < contract.discovery_spec.minimum_distinct_papers:
        raise ValueError("GAP_CANDIDATE_DISCOVERY_MINIMUM_DISTINCT_PAPERS_UNSATISFIED")
    payload = dict(type_payload) if isinstance(type_payload, dict) else {}
    missing_discovery_fields = [
        field_name
        for field_name in contract.payload_fields_for_phase(GapLifecyclePhase.DISCOVERY)
        if not _candidate_payload_value_present(payload.get(field_name))
    ]
    if missing_discovery_fields:
        raise ValueError(
            "GAP_CANDIDATE_DISCOVERY_PAYLOAD_INCOMPLETE:"
            + ",".join(sorted(missing_discovery_fields))
        )
    witness = dict(detection_witness) if isinstance(detection_witness, dict) else {}
    pattern_id = _clean(witness.get("pattern_id"))
    if not pattern_id:
        raise ValueError("GAP_CANDIDATE_REQUIRES_DETECTION_PATTERN_ID")
    witness_assertions = sorted(
        {
            _clean(item)
            for item in (witness.get("witness_assertion_ids") or canonical_assertion_ids)
            if _clean(item)
        }
    )
    if not set(witness_assertions).issubset(set(canonical_assertion_ids)):
        raise ValueError("GAP_CANDIDATE_WITNESS_ASSERTION_OUTSIDE_EVIDENCE_BUNDLE")
    context_reference = detection_context_ref(current_context)
    evidence_bundle = {
        "schema_version": SOURCE_BOUND_GAP_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "assertion_ids": canonical_assertion_ids,
        "source_units": units,
        "assertion_count": len(canonical_assertion_ids),
        "source_unit_count": len(units),
        "independent_paper_count": len(paper_ids),
        "paper_ids": paper_ids,
        "document_version_hashes": sorted(
            {
                _clean(unit.get("document_version_hash"))
                for unit in units
                if _clean(unit.get("document_version_hash"))
            }
        ),
        "scope_signature": {
            str(key): _clean(value)
            for key, value in (current_context.research_question_contract.get("scientific_scope") or {}).items()
            if _clean(value)
        },
        "condition_signatures": sorted(
            {
                _candidate_identity_material(unit.get("conditions") or {})
                for unit in units
            }
        ),
    }
    identity_material = {
        "factory_schema_version": SOURCE_BOUND_GAP_CANDIDATE_FACTORY_SCHEMA_VERSION,
        "gap_type": normalized_type.value,
        "gap_subtype": normalized_subtype,
        "contract_id": _clean(current_context.research_question_contract.get("contract_id")),
        "contract_revision": _clean(current_context.research_question_contract.get("contract_revision")),
        "graph_snapshot_ref": context_reference["graph_snapshot_ref"],
        "assertion_ids": canonical_assertion_ids,
        "source_units": [
            {
                "assertion_id": _clean(unit.get("assertion_id")),
                "source_span_id": _clean(unit.get("source_span_id")),
                "document_version_hash": _clean(unit.get("document_version_hash")),
            }
            for unit in units
        ],
        "type_payload": payload,
        "detector_id": _clean(detector_id),
        "detector_policy_version": _clean(detector_policy_version),
        "pattern_id": pattern_id,
    }
    if not identity_material["detector_id"] or not identity_material["detector_policy_version"]:
        raise ValueError("GAP_CANDIDATE_REQUIRES_VERSIONED_DETECTOR_IDENTITY")
    candidate_identity = "gapv3_" + sha256(
        _candidate_identity_material(identity_material).encode("utf-8")
    ).hexdigest()[:24]
    assessment = initial_gap_assessment(
        gap_type=normalized_type,
        signal_type=normalized_signal,
        candidate_stage=CandidateStage.RAW_CANDIDATE,
    )
    assessment["gap_subtype"] = normalized_subtype
    detection_provenance = {
        "schema_version": GAP_DETECTION_PROVENANCE_SCHEMA_VERSION,
        "detector_id": identity_material["detector_id"],
        "detector_policy_version": identity_material["detector_policy_version"],
        "detection_context_ref": context_reference,
        "graph_snapshot_ref": context_reference["graph_snapshot_ref"],
        "research_question_contract_id": context_reference["research_question_contract_id"],
        "contract_revision": context_reference["contract_revision"],
        "pattern_id": pattern_id,
        "witness_assertion_ids": witness_assertions,
        "witness_relation_ids": sorted(
            {_clean(item) for item in witness.get("witness_relation_ids") or [] if _clean(item)}
        ),
        "comparability_assessment_ids": sorted(
            {
                _clean(item)
                for item in witness.get("comparability_assessment_ids") or []
                if _clean(item)
            }
        ),
        "witness": {
            str(key): value
            for key, value in witness.items()
            if key not in {
                "pattern_id",
                "witness_assertion_ids",
                "witness_relation_ids",
                "comparability_assessment_ids",
            }
        },
    }
    candidate = {
        "schema_version": GAP_CANDIDATE_SCHEMA_VERSION,
        "gap_id": candidate_identity,
        "candidate_identity": candidate_identity,
        "project_id": _clean(current_context.project_id),
        "description": _clean(description),
        "sub_hypothesis_ids": [
            _clean(current_context.research_question_contract.get("sub_hypothesis_id"))
        ] if _clean(current_context.research_question_contract.get("sub_hypothesis_id")) else [],
        "research_question": dict(current_context.research_question_contract.get("research_question") or {}),
        "research_question_contract": dict(current_context.research_question_contract),
        "source_evidence_units": units,
        "source_lineage": list(units),
        "source_assertion_ids": canonical_assertion_ids,
        "assertion_ids": canonical_assertion_ids,
        "slot_support_ids": sorted({
            _clean(slot_support_id)
            for unit in units
            for slot_support_id in unit.get("slot_support_ids", [])
            if _clean(slot_support_id)
        }),
        "type_payload": payload,
        "detection_context_ref": context_reference,
        "detection_provenance": detection_provenance,
        "evidence_bundle": evidence_bundle,
        "gap_assessment": assessment,
        "evidence_graph_contract": {
            "schema_version": "heterogeneous_evidence_graph_binding_v3",
            "assertion_ids": canonical_assertion_ids,
            "source_span_ids": sorted(
                {_clean(unit.get("source_span_id")) for unit in units if _clean(unit.get("source_span_id"))}
            ),
            "document_version_hashes": evidence_bundle["document_version_hashes"],
            "research_question_contract_id": context_reference["research_question_contract_id"],
            "research_question_contract_revision": context_reference["contract_revision"],
            "detection_context_fingerprint": context_reference["detector_context_fingerprint"],
            "textual_explicitness": "EXPLICIT",
        },
    }
    return synchronize_candidate_surface(candidate, assessment)


def run_source_bound_gap_detection(
    project: dict[str, Any],
    *,
    limit: int | None = None,
    audit_candidate_budget_per_type_contract: int = 6,
    audit_frontier_resume_state_v3: dict[str, Any] | None = None,
    detector_checkpoint: dict[str, Any] | None = None,
    on_detector_complete: Any | None = None,
    load_detector_result: Any | None = None,
    detector_max_workers: int = 12,
) -> dict[str, Any]:
    """Run V3 source-span gap discovery without reading legacy causal graphs."""
    project = project if isinstance(project, dict) else {}
    try:
        try:
            from ._research_question_contract import research_question_cutover_audit_v3
            from ._subhypothesis_annotation import annotate_project_subhypotheses
        except ImportError:
            from _research_question_contract import research_question_cutover_audit_v3
            from _subhypothesis_annotation import annotate_project_subhypotheses
        cutover = research_question_cutover_audit_v3(project)
        if not cutover.get("all_subhypotheses_v3"):
            # This direct graph API is also a hard boundary: make stale
            # artefacts visible just as the persisted TanXi entrypoint does.
            annotate_project_subhypotheses(project)
            return {
                "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
                "evidence_graph": {
                    "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
                    "summary": {},
                },
                "candidates": [],
                "branch_states": [],
                "diagnostics": [{
                    "stage": "RESEARCH_QUESTION_CONTRACT",
                    "reason": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                    "cutover_audit": cutover,
                }],
                "summary": {
                    "candidate_count": 0,
                    "diagnostic_count": 1,
                    "detector_registry": [item.value for item in GapType],
                    "cutover_audit": cutover,
                },
            }
        annotate_project_subhypotheses(project)
    except Exception as exc:
        return {
            "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
            "evidence_graph": {"schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION, "summary": {}},
            "candidates": [],
            "branch_states": [],
            "diagnostics": [{"stage": "RESEARCH_QUESTION_CONTRACT", "reason": "V3_SH_CONSTRUCTION_FAILED", "detail": str(exc)}],
            "summary": {"candidate_count": 0, "diagnostic_count": 1, "detector_registry": [item.value for item in GapType]},
        }
    evidence_graph = {
        "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "assertions": [],
        "derived_inferences": [],
        "summary": {},
        "projection_source": RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
    }
    try:
        try:
            from ._gap_detectors import (
                run_registered_gap_detectors,
                select_fair_audit_frontier_v3,
            )
        except ImportError:
            from _gap_detectors import (
                run_registered_gap_detectors,
                select_fair_audit_frontier_v3,
            )
        graph_snapshot = project.get("_tanxi_graph_snapshot")
        if not isinstance(graph_snapshot, dict):
            raise ValueError(
                "TANXI_V3_GRAPH_SNAPSHOT_REQUIRED: Source-bound detector execution "
                "must receive the current detached research_evidence_graph_v4."
            )
        source_projection = graph_snapshot.get("source_assertion_projection") if isinstance(graph_snapshot.get("source_assertion_projection"), dict) else {}
        evidence_graph = {
            "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
            "assertions": list(source_projection.get("assertions") or []),
            "derived_inferences": list(source_projection.get("derived_inferences") or []),
            "summary": dict(source_projection.get("summary") or {}),
            # The public report retains only V3's frozen projection; it does
            # not expose a separately rebuilt operational graph.
            "projection_source": RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        }
        detector_run = run_registered_gap_detectors(
            project,
            graph_snapshot,
            corpus_summary=dict(evidence_graph.get("summary") or {}),
            checkpoint=detector_checkpoint,
            on_detector_complete=on_detector_complete,
            load_detector_result=load_detector_result,
            max_workers=max(1, min(12, int(detector_max_workers or 1))),
        )
        candidates = [item for item in detector_run.get("candidates", []) if isinstance(item, dict)]
        diagnostics = [item for item in detector_run.get("diagnostics", []) if isinstance(item, dict)]
    except Exception as exc:
        candidates = []
        diagnostics = [{"stage": "TYPE_DIRECTED_DETECTOR", "reason": "REGISTRY_EXECUTION_FAILED", "detail": str(exc)}]
    requested_audit_budget = (
        int(limit)
        if limit is not None
        else int(audit_candidate_budget_per_type_contract)
    )
    audit_frontier = select_fair_audit_frontier_v3(
        candidates,
        per_type_contract_budget=requested_audit_budget,
        resume_state=audit_frontier_resume_state_v3,
    )
    resume_validation = (
        audit_frontier.get("resume_validation")
        if isinstance(audit_frontier.get("resume_validation"), dict)
        else {}
    )
    if str(resume_validation.get("status") or "") == "REJECTED":
        diagnostics.append(
            {
                "schema_version": "retrieval_diagnostic_v3",
                "stage": "SEMANTIC_AUDIT_FRONTIER",
                "outcome": "BLOCKED",
                "reason_code": str(
                    resume_validation.get("reason_code")
                    or "AUDIT_FRONTIER_CURSOR_REJECTED"
                ),
                "evidence_ids": [],
                "retry_recommended": False,
            }
        )
    candidates = list(audit_frontier["selected_candidates"])
    branch_states = _v3_branch_diagnostics(project, evidence_graph, candidates, diagnostics)
    return {
        "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "evidence_graph": evidence_graph,
        "candidates": candidates,
        "branch_states": branch_states,
        "diagnostics": diagnostics[:100],
        "summary": {
            "candidate_count": len(candidates),
            "detected_candidate_count": len(audit_frontier["continuation_frontier"]),
            "audit_candidate_budget_per_type_contract": int(
                audit_frontier["per_type_contract_budget"]
            ),
            "audit_continuation_candidate_count": len(
                [
                    item
                    for item in audit_frontier["continuation_frontier"]
                    if item.get("selection_status") == "DEFERRED_PENDING_AUDIT_BUDGET"
                ]
            ),
            "audit_candidate_count_by_bucket": dict(
                audit_frontier["candidate_count_by_bucket"]
            ),
            "audit_frontier_resume_validation": dict(resume_validation),
            "candidate_count_by_stage": dict(Counter(str((item.get("gap_assessment") or {}).get("candidate_stage") or "") for item in candidates)),
            "candidate_count_by_type": dict(Counter(str(item.get("gap_type") or "") for item in candidates)),
            "diagnostic_count": len(diagnostics),
            "detector_registry": list(detector_run.get("registered_gap_types") or [item.value for item in GapType]) if 'detector_run' in locals() else [item.value for item in GapType],
            "research_graph_snapshot_ref": (
                detector_run.get("graph_snapshot_ref")
                if isinstance(detector_run.get("graph_snapshot_ref"), dict)
                else {}
            ) if 'detector_run' in locals() else {},
            "detector_execution_metrics": (
                dict(detector_run.get("execution_metrics") or {})
                if 'detector_run' in locals()
                else {}
            ),
            **dict(evidence_graph.get("summary") or {}),
        },
        "audit_continuation_frontier_v3": list(
            audit_frontier["continuation_frontier"]
        ),
        "audit_frontier_resume_state_v3": dict(
            audit_frontier.get("resume_state_v3") or {}
        ),
    }
