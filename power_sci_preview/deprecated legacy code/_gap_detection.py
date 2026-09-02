from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from hashlib import sha256
from typing import Any, Callable, Literal
import ast
import copy
import json
import re
import time

try:
    from .log import log_event
except ImportError:
    from log import log_event

try:
    from ._gap_types import GapRoute, GapType, assessment_of, group_by_gap_type, group_by_route, group_by_semantic_status, is_primary_mechanism_candidate, is_primary_research_candidate, synchronize_candidate_surface
    from ._gap_semantic_audit import audit_gap_candidate_semantics, normalize_semantic_confidence
    from ._gap_retrieval import (
        apply_gap_resolution_retrieval_cycle_v3,
        build_gap_resolution_work_item_v3,
        build_slot_directed_recovery_plan,
        plan_targeted_retrieval,
        qualify_gap_candidate,
        rebind_candidate_with_retrieved_evidence,
        run_targeted_retrieval_cycle,
    )
    from ._research_packages import build_research_package, build_research_packages, group_research_packages_by_kind, select_research_package_candidates
    from ._research_graph import RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION, bind_candidate_to_graph_snapshot, graph_snapshot_ref
    from ._type_directed_evidence import type_directed_missing_axes
    from ._research_question_contract import research_question_cutover_audit_v3
except ImportError:
    from _gap_types import GapRoute, GapType, assessment_of, group_by_gap_type, group_by_route, group_by_semantic_status, is_primary_mechanism_candidate, is_primary_research_candidate, synchronize_candidate_surface
    from _gap_semantic_audit import audit_gap_candidate_semantics, normalize_semantic_confidence
    from _gap_retrieval import (
        apply_gap_resolution_retrieval_cycle_v3,
        build_gap_resolution_work_item_v3,
        build_slot_directed_recovery_plan,
        plan_targeted_retrieval,
        qualify_gap_candidate,
        rebind_candidate_with_retrieved_evidence,
        run_targeted_retrieval_cycle,
    )
    from _research_packages import build_research_package, build_research_packages, group_research_packages_by_kind, select_research_package_candidates
    from _research_graph import RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION, bind_candidate_to_graph_snapshot, graph_snapshot_ref
    from _type_directed_evidence import type_directed_missing_axes
    from _research_question_contract import research_question_cutover_audit_v3


EVIDENCE_DERIVED_GAP_GENERATOR_TYPES = frozenset(
    {
        "direct_mechanism_gap",
        "mechanism_gap",
        "mechanism_problem",
        "causal_chain_break",
        "causal_mediation_unresolved",
        "edge_specific_unknown",
        "declared_missing_edge",
        "mechanism_discrimination_gap",
        "measurement_gap",
        "contradiction",
        "anomaly",
        "theory_observation_mismatch",
        "cross_hypothesis_coupling",
        "conflict_boundary_gap",
        "primary_claim_reversal_gap",
        "noncore_evidence_integration_gap",
    }
)
SECONDARY_RESEARCH_OPPORTUNITY_TYPES = frozenset(
    {
        "combinatorial",
        "improvement",
        "migration",
        "community_combinatorial",
        "structural",
        "isolated_node",
        "low_degree_node",
    }
)
MECHANISTIC_PRIORITY_WEIGHTS = {
    "direct_gap_signal": 0.30,
    "causal_bottleneck": 0.25,
    "contradiction_or_anomaly": 0.20,
    "evidence_strength_and_context_match": 0.15,
    "scientific_or_strategic_impact": 0.10,
}
MECHANISTIC_PRIORITY_MATRIX_AUXILIARY_CAP = 0.05

PRIMARY_MECHANISM_CANDIDATE_POOL = "PRIMARY_MECHANISM_CANDIDATE_POOL"
SECONDARY_RESEARCH_OPPORTUNITY_POOL = "SECONDARY_RESEARCH_OPPORTUNITY_POOL"
EVIDENCE_EXTRACTION_SHORTAGE_POOL = "EVIDENCE_EXTRACTION_SHORTAGE_POOL"
COMPOSITE_GAP_AUDIT_POOL = "COMPOSITE_GAP_AUDIT_POOL"
GAP_EXISTENCE_VERIFICATION_POOL = "GAP_EXISTENCE_VERIFICATION_POOL"
REJECTED_EVIDENCE_AUDIT_POOL = "REJECTED_EVIDENCE_AUDIT_POOL"


def _project_uses_research_question_evidence_v3(project: dict[str, Any]) -> bool:
    """Identify a *complete* hard-cutover project without reading v1 cues."""
    audit = research_question_cutover_audit_v3(project)
    return bool(audit["all_subhypotheses_v3"])
MECHANISM_DISCOVERY_LEAD_POOL = "MECHANISM_DISCOVERY_LEAD_POOL"
LANDSCAPE_DIAGNOSTIC_POOL = "LANDSCAPE_DIAGNOSTIC_POOL"
REJECTED_SCIENTIFIC_CANDIDATE_POOL = "REJECTED_SCIENTIFIC_CANDIDATE_POOL"

LANDSCAPE_DIAGNOSTIC_TYPES = frozenset({
    "combinatorial", "improvement", "community_combinatorial",
    "structural", "isolated_node", "low_degree_node", "migration",
})

# This only supports deterministic relevance summaries for already-admitted
# source-bound gaps.  It is not a domain keyword policy and never decides
# whether a candidate may enter the evidence graph.
_MECHANISM_NOISE_TERMS = frozenset({
    "analysis", "approach", "benchmark", "challenge", "comprehensive", "data", "evidence",
    "framework", "literature", "method", "methods", "model", "paper", "research", "review",
    "study", "studies", "system", "systems", "validation",
})


@dataclass
class EvidencePathStatus:
    core_effect: Literal["supported", "mixed", "unsupported", "untested"]
    adverse_reversal: Literal["found", "not_found", "untested"]
    boundary_generalization: Literal["defined", "partial", "missing", "untested"]
    conflict_taxonomy: list[str] = field(default_factory=list)

SOURCE_ALIGNMENT_VERDICTS = frozenset({
    "DIRECTLY_ALIGNED", "PARTIALLY_ALIGNED", "RATIONALE_ALIGNED",
    "OUT_OF_SCOPE", "UNVERIFIABLE_SOURCE",
})
GAP_EPISTEMIC_VERDICTS = frozenset({
    "EXPLICIT_AUTHOR_STATED_GAP", "COMPOSITE_CONTRADICTION_GAP",
    "COMPOSITE_CAUSAL_MEDIATION_GAP", "THEORY_OBSERVATION_MISMATCH",
    "BOUNDARY_CONDITION_GAP", "NO_GAP_PREDICATE",
    "COMPOSITE_TABI_GAP", "EVIDENCE_EXTRACTION_SHORTAGE",
    "ANOMALY_CORROBORATION_REQUIRED",
})
CAUSAL_READINESS_VERDICTS = frozenset({
    "CAUSAL_CHAIN_VALID", "INPUT_INVALID", "MEDIATOR_INVALID",
    "OUTCOME_INVALID", "MODE_UNRESOLVED", "SOURCE_ROLE_CONFLICT",
})
PRIMARY_ACCEPTED_GAP_EPISTEMIC_VERDICTS = frozenset({
    "EXPLICIT_AUTHOR_STATED_GAP",
    "COMPOSITE_CONTRADICTION_GAP",
    "COMPOSITE_CAUSAL_MEDIATION_GAP",
    "THEORY_OBSERVATION_MISMATCH",
    "BOUNDARY_CONDITION_GAP",
    "COMPOSITE_TABI_GAP",
})

# Scientific nouns identify an axis; only an epistemic predicate establishes
# that the source is actually describing missing knowledge.  The patterns are
# deliberately field-neutral so the same boundary applies to physics,
# chemistry, biology, materials, engineering, and computational research.
_EXPLICIT_GAP_PREDICATE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unknown_or_unresolved", (
        "remain unknown", "remains unknown", "is unknown", "remain unclear", "remains unclear",
        "not well understood", "poorly understood", "unresolved", "mechanism is unclear",
        "mechanism remains unclear", "mechanism is unknown", "has not been established",
        "have not been established", "not established", "open problem", "open question",
        "remains an open problem", "remains an open question", "尚不清楚", "仍不清楚", "尚未建立", "未知机制",
        "机制不明", "机制尚不明确", "有待阐明", "尚待阐明", "有待研究", "仍待探索",
        "未得到充分阐释", "缺乏清晰解释", "尚无定论",
    )),
    ("not_tested", (
        "not tested", "has not been tested", "have not been tested", "not evaluated",
        "not examined", "not investigated", "has yet to be tested", "remains to be tested",
        "未测试", "尚未测试", "尚未验证", "未经验证", "有待验证", "有待检验", "未予检验",
    )),
    ("explanatory_failure", (
        "cannot explain", "does not explain", "fails to explain", "unable to explain",
        "inconsistent evidence", "conflicting evidence", "conflicting results", "contradictory evidence",
        "cannot account for", "does not account for", "unexplained", "not explained",
        "discrepancy remains", "mismatch remains", "无法解释", "尚无法解释", "证据冲突", "结果矛盾",
        "结论不一致", "观察结果与理论不符", "存在分歧",
    )),
    ("explicit_limitation_or_failure", (
        "limited by", "is limited by", "are limited by", "fails under", "failure under",
        "lack of evidence", "insufficient evidence", "missing evidence", "no evidence for",
        "bottleneck remains", "major limitation", "key limitation", "受限于", "证据不足", "缺乏证据",
        "缺少直接证据", "关键瓶颈", "仍存在局限", "尚未解决",
    )),
)

_GAP_PROVENANCE_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "change", "data", "for", "from", "in", "into",
    "measurement", "method", "model", "of", "on", "or", "system", "the", "thermal", "to",
    "under", "using", "via", "with", "within",
}



def add_literature_evidence(
    project_id: str,
    title: str,
    citation: str,
    method: str,
    scenario: str,
    benchmark: str,
    contribution: str,
    limitation: str,
    url: str = "",
) -> str:
    """Retired direct EvidenceV1 writer.

    Scientific evidence must enter through the V3 importer so it obtains a
    document version, bounded source spans, and (when explicitly linked) a
    question-contract assertion projection.  The old method/scenario fields
    are not a substitute for those source records.
    """
    del title, citation, method, scenario, benchmark, contribution, limitation, url
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    return json.dumps(
        {
            "schema_version": "research_question_evidence_v3",
            "project_id": project_id,
            "status": "LEGACY_DIRECT_EVIDENCE_WRITER_RETIRED",
            "imported": False,
            "legacy_causal_artifacts_accepted": False,
            "next_step": (
                "Use import_literature_text or import_papergraph_record with "
                "source text and an explicit V3 sub-hypothesis binding."
            ),
            "cutover_status": research_question_cutover_audit_v3(project),
        },
        ensure_ascii=False,
        indent=2,
    )

def build_knowledge_map(project_id: str, dimension: str = "method-scenario-benchmark") -> str:
    """Retired causal-map entrypoint.

    The V3 research-question pipeline uses the heterogeneous assertion graph
    constructed by TanXi.  This function is retained only as an explicit
    migration boundary so callers receive an actionable response instead of
    recreating ``causal_evidence_graph`` on a current or stale project.
    """
    del dimension
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    cutover = research_question_cutover_audit_v3(project)
    return json.dumps(
        {
            "schema_version": "research_question_evidence_v3",
            "project_id": project_id,
            "status": "LEGACY_CAUSAL_KNOWLEDGE_MAP_RETIRED",
            "cutover_audit": cutover,
            "legacy_causal_artifacts_accepted": False,
            "next_step": (
                "Use execute_research_question_retrieval_plan followed by "
                "run_tanxi_gap_exploration; the V2 pipeline builds a "
                "heterogeneous source-span assertion graph."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
def build_knowledge_map_payload(
    records: list[dict[str, Any]],
    *,
    dimension: str = "method-scenario-benchmark",
    active_papergraph_count: int | None = None,
    extraction_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an explicit retirement marker for the V1 M-S-B map.

    A method/scenario/benchmark matrix cannot stand in for the V3
    heterogeneous evidence graph.  Returning a marker instead of a partial
    map prevents legacy callers from seeing a newly generated causal graph
    and treating it as compatible evidence.
    """
    del records, active_papergraph_count, extraction_repair
    return {
        "schema_version": "research_question_evidence_v3",
        "status": "LEGACY_METHOD_SCENARIO_BENCHMARK_MAP_RETIRED",
        "dimension": dimension,
        "legacy_causal_artifacts_status": "STALE_SCHEMA",
        "legacy_causal_artifacts_accepted": False,
        "next_step": (
            "Use a ResearchQuestionContractV3 retrieval plan and the "
            "heterogeneous source-span assertion graph."
        ),
    }

def admitted_method_scenario_benchmark_records(
    records: list[dict[str, Any]],
    *,
    allow_noncore_context: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return source-grounded, non-background M-S-B triples plus an audit trail.

    The same admission function is deliberately shared by map construction,
    Louvain, and gap-generation paths. A malformed descriptor must therefore
    be unable to appear in one graph while being rejected by another.
    """
    try:
        from ._literature_import import assess_structured_descriptor, authoritative_descriptor_source_text
        from ._utils import trim_text
    except ImportError:
        from _literature_import import assess_structured_descriptor, authoritative_descriptor_source_text
        from _utils import trim_text

    admitted: list[dict[str, Any]] = []
    rejected_by_reason: Counter[str] = Counter()
    rejected_samples: list[dict[str, Any]] = []
    admitted_by_tier: Counter[str] = Counter()

    def reject(record: dict[str, Any], reason: str, details: dict[str, Any] | None = None) -> None:
        rejected_by_reason[reason] += 1
        if len(rejected_samples) >= 12:
            return
        identity = str(record.get("paper_id") or record.get("citation") or record.get("title") or "unidentified record")
        sample = {"record": trim_text(identity, 240), "reason": reason}
        if details:
            sample["descriptor_assessments"] = details
        rejected_samples.append(sample)

    for record in records:
        if not isinstance(record, dict):
            rejected_by_reason["invalid_record"] += 1
            continue
        if record.get("active", True) is False:
            reject(record, "inactive_record")
            continue
        paper_genre = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
        alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        is_background_or_review = bool(
            paper_genre.get("is_review")
            or str(record.get("evidence_kind") or "") == "background_review"
            or str(record.get("evidence_role") or alignment.get("evidence_role") or "") == "background_review"
        )
        core_explicitly_false = bool(
            alignment.get("core_eligible") is False
            or record.get("core_eligible") is False
        )
        context_related = bool(
            record.get("corpus_admitted") is True
            or alignment.get("corpus_admitted") is True
            or record.get("auxiliary_eligible") is True
            or alignment.get("auxiliary_eligible") is True
            or record.get("fulltext_structurally_usable") is True
            or record.get("fulltext_evidence_admissible") is True
        )
        if is_background_or_review and not (allow_noncore_context and context_related):
            reject(record, "background_or_review_record")
            continue
        if core_explicitly_false and not (allow_noncore_context and context_related):
            reject(record, "not_core_eligible")
            continue
        source_text = authoritative_descriptor_source_text(record)
        assessments = {
            field: assess_structured_descriptor(record.get(field, ""), field, source_text)
            for field in ("method", "scenario", "benchmark")
        }
        rejected_fields = [field for field, assessment in assessments.items() if not assessment.get("accepted")]
        if rejected_fields:
            reject(
                record,
                "descriptor_rejected",
                {field: assessments[field] for field in rejected_fields},
            )
            for field in rejected_fields:
                rejected_by_reason[f"{field}:{assessments[field].get('reason') or 'rejected'}"] += 1
            continue
        if is_background_or_review:
            admission_tier = "BACKGROUND_CONTEXT"
        elif core_explicitly_false:
            admission_tier = "NONCORE_CONTEXT"
        else:
            admission_tier = "CORE_DIRECT"
        sanitized = dict(record)
        sanitized.update({field: str(assessments[field]["value"]) for field in assessments})
        quality = dict(sanitized.get("extraction_quality") or {})
        quality["msb_descriptor_admission"] = assessments
        quality["msb_descriptor_source"] = "title_abstract_conclusion_only"
        sanitized["extraction_quality"] = quality
        sanitized["msb_admission_tier"] = admission_tier
        sanitized["evidence_scope"] = (
            "core_direct"
            if admission_tier == "CORE_DIRECT"
            else "background_context"
            if admission_tier == "BACKGROUND_CONTEXT"
            else "noncore_context"
        )
        sanitized["context_only"] = admission_tier != "CORE_DIRECT"
        sanitized["direct_claim_support"] = admission_tier == "CORE_DIRECT"
        if admission_tier != "CORE_DIRECT":
            sanitized["claim_strength_effect"] = "no_claim_strength_increase"
            sanitized["supports_primary_claim"] = False
        admitted.append(sanitized)
        admitted_by_tier[admission_tier] += 1

    audit = {
        "schema_version": "msb_descriptor_admission_v2",
        "source_policy": "title_abstract_conclusion_only",
        "allow_noncore_context": allow_noncore_context,
        "input_records": len(records),
        "admitted_records": len(admitted),
        "admitted_core_records": int(admitted_by_tier.get("CORE_DIRECT", 0)),
        "admitted_noncore_context_records": int(admitted_by_tier.get("NONCORE_CONTEXT", 0)),
        "admitted_background_context_records": int(admitted_by_tier.get("BACKGROUND_CONTEXT", 0)),
        "admitted_by_tier": dict(sorted(admitted_by_tier.items())),
        "rejected_records": max(0, len(records) - len(admitted)),
        "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        "rejected_samples": rejected_samples,
    }
    return admitted, audit


def run_method_scenario_benchmark_louvain(
    records: list[dict[str, Any]],
    resolution: float = 1.0,
    *,
    allow_noncore_context: bool = False,
) -> dict[str, Any]:
    """Detect weighted research branches in the method-scenario-benchmark evidence graph.

    This is intentionally separate from citation Louvain: an edge here means
    that one imported record supplies evidence for two research descriptors.
    It must never be presented as a paper-to-paper citation edge.
    """
    admitted_records, admission_audit = admitted_method_scenario_benchmark_records(
        records,
        allow_noncore_context=allow_noncore_context,
    )
    try:
        import networkx as nx
    except ImportError:
        return {
            "status": "unavailable",
            "reason": "networkx is not installed",
            "graph_type": "method_scenario_benchmark_evidence",
            "num_communities": 0,
            "communities": [],
            "admission": admission_audit,
        }

    graph = nx.Graph()
    edge_support: dict[tuple[str, str], set[str]] = defaultdict(set)
    usable_records = 0

    def add_descriptor(kind: str, value: str) -> str:
        node_id = f"{kind}:{value.lower()}"
        graph.add_node(node_id, kind=kind, label=value)
        return node_id

    def is_known(value: str) -> bool:
        lowered = value.strip().lower()
        return bool(lowered) and not lowered.startswith(("unknown", "unspecified", "not reported", "n/a"))

    def record_weight(record: dict[str, Any]) -> float:
        try:
            quality = float(record.get("publication_quality_score") or 0.5)
        except (TypeError, ValueError):
            quality = 0.5
        try:
            citations = float(record.get("citation_count") or 0.0)
        except (TypeError, ValueError):
            citations = 0.0
        return round(max(0.25, min(1.0, quality)) * (1.0 + min(0.5, citations / 100.0)), 4)

    for record in admitted_records:
        method = str(record["method"])
        scenario = str(record["scenario"])
        benchmark = str(record["benchmark"])
        descriptors = [
            ("method", method),
            ("scenario", scenario),
            ("benchmark", benchmark),
        ]
        nodes = [add_descriptor(kind, value) for kind, value in descriptors if is_known(value)]
        if len(nodes) < 2:
            continue
        usable_records += 1
        citation = str(record.get("citation") or record.get("paper_id") or record.get("title") or "")
        weight = record_weight(record)
        for left_index, source in enumerate(nodes):
            for target in nodes[left_index + 1:]:
                edge_key = tuple(sorted((source, target)))
                if graph.has_edge(source, target):
                    graph[source][target]["weight"] += weight
                    graph[source][target]["record_count"] += 1
                else:
                    graph.add_edge(source, target, weight=weight, record_count=1)
                if citation:
                    edge_support[edge_key].add(citation)

    base = {
        "graph_type": "method_scenario_benchmark_evidence",
        "edge_basis": "weighted co-occurrence in admitted source-grounded evidence triples; not citation edges",
        "record_count": usable_records,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "resolution_used": max(0.1, min(5.0, float(resolution))),
        "num_communities": 0,
        "modularity": None,
        "community_map": {},
        "communities": [],
        "admission": admission_audit,
    }
    if graph.number_of_nodes() < 3 or graph.number_of_edges() < 2:
        return {**base, "status": "insufficient_structure", "reason": "Need at least three known descriptors and two evidence edges."}
    try:
        raw_communities = nx.algorithms.community.louvain_communities(
            graph,
            weight="weight",
            resolution=base["resolution_used"],
            seed=42,
        )
        ordered = sorted((set(community) for community in raw_communities), key=lambda members: (-len(members), sorted(members)))
        community_map = {
            node_id: community_id
            for community_id, members in enumerate(ordered)
            for node_id in members
        }
        modularity = nx.algorithms.community.modularity(graph, ordered, weight="weight", resolution=base["resolution_used"])
    except Exception as exc:
        return {**base, "status": "failed", "reason": f"Louvain failed: {str(exc)[:240]}"}

    communities = []
    for community_id, members in enumerate(ordered):
        member_set = set(members)
        weighted_support = 0.0
        references: set[str] = set()
        for source, target, attributes in graph.edges(member_set, data=True):
            if source not in member_set or target not in member_set:
                continue
            weighted_support += float(attributes.get("weight") or 0.0)
            references.update(edge_support.get(tuple(sorted((source, target))), set()))
        descriptors = {
            kind: sorted(
                str(graph.nodes[node_id].get("label") or "")
                for node_id in member_set
                if graph.nodes[node_id].get("kind") == kind
            )
            for kind in ("method", "scenario", "benchmark")
        }
        communities.append(
            {
                "community_id": community_id,
                "size": len(member_set),
                "methods": descriptors["method"],
                "scenarios": descriptors["scenario"],
                "benchmarks": descriptors["benchmark"],
                "internal_weight": round(weighted_support, 4),
                "supporting_references": sorted(references)[:8],
            }
        )
    return {
        **base,
        "status": "success",
        "num_communities": len(communities),
        "modularity": round(float(modularity), 6),
        "community_map": community_map,
        "communities": communities,
    }


def annotate_gap_with_method_scenario_benchmark_communities(
    gap: dict[str, Any],
    analysis: dict[str, Any],
) -> None:
    """Attach evidence-graph community scope without claiming citation membership."""
    if not isinstance(analysis, dict) or analysis.get("status") != "success":
        return
    ingredients = gap.get("hypothesis_ingredients", {}) if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    values_by_kind = {
        "method": ingredients.get("methods", gap.get("method", "")),
        "scenario": ingredients.get("scenarios", gap.get("scenario", "")),
        "benchmark": ingredients.get("benchmarks", gap.get("benchmark", "")),
    }
    community_map = analysis.get("community_map", {}) if isinstance(analysis.get("community_map"), dict) else {}
    community_ids: set[int] = set()
    for kind, values in values_by_kind.items():
        candidates = values if isinstance(values, list) else [values]
        for value in candidates:
            node_id = f"{kind}:{str(value or '').strip().lower()}"
            if node_id in community_map:
                community_ids.add(int(community_map[node_id]))
    if not community_ids:
        return
    gap["method_scenario_benchmark_louvain_communities"] = sorted(community_ids)
    gap["method_scenario_benchmark_louvain_scope"] = "weighted_evidence_cooccurrence"
    if len(community_ids) == 1:
        gap["method_scenario_benchmark_louvain_primary_community"] = next(iter(community_ids))


def louvain_record_match_keys(record: dict[str, Any]) -> set[str]:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    keys: set[str] = set()
    for field in ("unique_key", "node_id", "doi", "arxiv_id", "semantic_scholar_id", "url", "title"):
        value = str(record.get(field) or "").strip()
        if not value:
            continue
        normalized = normalize_key(value)
        if normalized:
            keys.add(normalized)
        if field == "doi":
            keys.add(normalize_key(f"doi:{value}"))
        elif field == "arxiv_id":
            keys.add(normalize_key(f"arxiv:{value}"))
        elif field == "semantic_scholar_id":
            keys.add(normalize_key(f"s2:{value}"))
    return {key for key in keys if key}


def louvain_community_gap_candidates(
    project: dict[str, Any],
    community_maps: dict[str, Any],
    *,
    max_per_community: int = 2,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for community_id, payload in community_maps.items():
        if not isinstance(payload, dict) or not payload.get("eligible_for_gap_analysis"):
            continue
        knowledge_map = payload.get("knowledge_map") if isinstance(payload.get("knowledge_map"), dict) else {}
        method_coverage = knowledge_map.get("method_scenario_coverage", {})
        methods = [str(item) for item in knowledge_map.get("main_methods", []) if str(item) and str(item) != "unknown"]
        scenarios = [str(item) for item in knowledge_map.get("main_scenarios", []) if str(item) and str(item) != "unknown"]
        emitted = 0
        for method in methods:
            for scenario in scenarios:
                if scenario in set(method_coverage.get(method, [])):
                    continue
                references = []
                for triple in knowledge_map.get("method_scenario_benchmark_triples", []):
                    if not isinstance(triple, dict):
                        continue
                    if triple.get("method") == method or triple.get("scenario") == scenario:
                        references.extend(str(ref) for ref in triple.get("references", []) if ref)
                gap = make_gap(
                    gap_type="community_combinatorial",
                    description=(
                        f"Within Louvain community {community_id} ({payload.get('primary_field') or 'mixed field'}), "
                        f"method '{method}' has no imported evidence in scenario '{scenario}'."
                    ),
                    supporting_references=list(dict.fromkeys(references))[:6],
                    suggested_research_path=(
                        "Run a targeted within-community validation using the community's representative papers and explicit "
                        "method-scenario benchmarks before claiming a cross-community transfer."
                    ),
                    value_argument=(
                        "The absence is measured inside a citation-defined research branch, so it is more specific than a "
                        "global method-scenario gap."
                    ),
                )
                gap["louvain_community"] = int(community_id)
                gap["louvain_primary_field"] = payload.get("primary_field")
                gap["louvain_community_record_count"] = payload.get("record_count", 0)
                gap["louvain_gap_scope"] = "within_community"
                candidates.append(assess_gap_dict(project, gap))
                emitted += 1
                if emitted >= max(1, int(max_per_community)):
                    break
            if emitted >= max(1, int(max_per_community)):
                break
    return candidates


def build_louvain_community_knowledge_maps(
    project_id: str,
    relation_graph_id: str = "",
    min_records: int | None = None,
) -> str:
    """Retire V1 community M-S-B maps instead of producing stale snapshots."""
    del relation_graph_id, min_records
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    return json.dumps(
        {
            "schema_version": "research_question_evidence_v3",
            "project_id": project_id,
            "status": "LEGACY_LOUVAIN_KNOWLEDGE_MAP_RETIRED",
            "communities": {},
            "legacy_causal_artifacts_status": "STALE_SCHEMA",
            "legacy_causal_artifacts_accepted": False,
            "next_step": (
                "Use V3 research-question retrieval plans and the "
                "heterogeneous evidence graph; community M-S-B maps are not "
                "a compatible gap-analysis input."
            ),
            "cutover_status": research_question_cutover_audit_v3(project),
        },
        ensure_ascii=False,
        indent=2,
    )

def causal_context_from_record(record: dict[str, Any]) -> dict[str, str]:
    keys = {
        "research_object": ("research_object", "subject", "object", "scenario"),
        "species_or_system": ("species", "organism", "system", "model"),
        "model_or_sample": ("cell_model", "model_system", "sample", "cohort"),
        "stage_or_regime": ("developmental_stage", "reprogramming_stage", "stage", "operating_regime", "condition"),
        "timepoint": ("timepoint", "time_point", "measurement_time", "duration"),
        "method": ("method",),
        "spatial_scale": ("spatial_scale", "scale", "depth", "location"),
        "temporal_scale": ("temporal_scale", "time_scale", "duration"),
        "environmental_context": ("environmental_context", "environment", "chemical_environment", "medium"),
        "intervention_context": ("intervention_context", "intervention", "perturbation", "treatment"),
        "measurement_definition": ("measurement_definition", "measurement", "readout_definition", "assay"),
        "outcome_definition": ("outcome_definition", "endpoint_definition", "benchmark"),
        "transfer_justification": ("transfer_justification", "mapping_justification", "translation_evidence"),
    }
    context: dict[str, str] = {}
    for name, candidates in keys.items():
        value = next((str(record.get(key) or "").strip() for key in candidates if str(record.get(key) or "").strip()), "")
        if value:
            context[name] = value
    return context


def build_causal_evidence_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Retire the V1 causal-edge graph without approximating it in V2."""
    del records
    return {
        "schema_version": "research_question_evidence_v3",
        "status": "LEGACY_CAUSAL_EVIDENCE_GRAPH_RETIRED",
        "legacy_causal_artifacts_status": "STALE_SCHEMA",
        "legacy_causal_artifacts_accepted": False,
        "nodes": [],
        "edges": [],
        "chains": [],
        "next_step": (
            "Use the current research_evidence_graph_v4 through TanXi V3; "
            "causal edges alone are not a V3 evidence artifact."
        ),
    }

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    chains: list[dict[str, Any]] = []
    non_causal_claims: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str, str]] = set()

    def add_node(label: Any, node_type: str, citation: str) -> str:
        text = str(label or "").strip()
        if not text:
            return ""
        key = canonical_causal_node_key(text)
        item = nodes.setdefault(
            key,
            {"id": f"node_{len(nodes) + 1}", "label": text, "canonical_label": key, "types": [], "supporting_references": []},
        )
        if node_type not in item["types"]:
            item["types"].append(node_type)
        if citation and citation not in item["supporting_references"]:
            item["supporting_references"].append(citation)
        return item["id"]

    def add_edge(
        source: str,
        target: str,
        relation: str,
        citation: str,
        excerpt: str,
        evidence_type: str,
        *,
        polarity: str = "",
        modality: str = "",
        source_location: dict[str, Any] | None = None,
        confidence: Any = None,
        context: dict[str, str] | None = None,
        interventions: list[Any] | None = None,
        paper_id: str = "",
        sub_hypothesis_id: str = "",
        source_evidence: dict[str, Any] | None = None,
    ) -> bool:
        if not source or not target:
            return False
        key = (source, target, relation, citation)
        if key in edge_keys:
            return False
        edge_keys.add(key)
        edge = {
            "source": source,
            "target": target,
            "relation": relation,
            "citation": citation,
            "evidence_excerpt": str(excerpt or "")[:600],
            "evidence_type": evidence_type or "reported_unclassified",
            "paper_id": str(paper_id or ""),
            "sub_hypothesis_id": str(sub_hypothesis_id or ""),
        }
        if polarity:
            edge["polarity"] = polarity
        if modality:
            edge["modality"] = modality
        if isinstance(source_location, dict) and source_location:
            edge["source_location"] = dict(source_location)
        if isinstance(confidence, (int, float)):
            edge["confidence"] = float(confidence)
        if isinstance(context, dict) and context:
            edge["context"] = dict(context)
        if isinstance(interventions, list):
            edge["interventions"] = [str(item) for item in interventions if str(item).strip()][:8]
        if isinstance(source_evidence, dict) and source_evidence:
            edge["source_evidence"] = dict(source_evidence)
            edge["source_unit_id"] = str(source_evidence.get("source_unit_id") or "")
            edge["excerpt_hash"] = str(source_evidence.get("excerpt_hash") or "")
        edges.append(edge)
        return True

    for record in records:
        citation = record_reference(record)
        paper_id = str(record.get("paper_id") or record.get("doi") or "")
        sub_hypothesis_id = str(record.get("retrieval_branch") or record.get("sub_hypothesis_id") or "")
        record_context = causal_context_from_record(record)
        raw_chains = record.get("causal_chains", [])
        for chain in raw_chains if isinstance(raw_chains, list) else []:
            if not isinstance(chain, dict):
                continue
            chain_context = chain.get("context") if isinstance(chain.get("context"), dict) else {}
            edge_context = {**record_context, **{str(key): str(value) for key, value in chain_context.items() if str(value).strip()}}
            if chain.get("causal_claim") is False or str(chain.get("modality") or "") == "speculative":
                non_causal_claims.append(
                    {
                        "paper_id": str(record.get("paper_id") or ""),
                        "citation": citation,
                        "trigger": str(chain.get("trigger") or ""),
                        "outcome": str(chain.get("outcome") or ""),
                        "relation": str(chain.get("relation") or ""),
                        "modality": str(chain.get("modality") or "speculative"),
                        "evidence": str(chain.get("outcome_evidence") or chain.get("trigger_evidence") or "")[:600],
                    }
                )
                continue
            trigger_id = add_node(chain.get("trigger"), "external_intervention_or_condition", citation)
            prior_id = trigger_id
            edge_indexes: list[int] = []
            raw_steps = chain.get("steps", [])
            raw_observables = chain.get("observables", [])
            raw_interventions = chain.get("interventions", [])
            for step in raw_steps if isinstance(raw_steps, list) else []:
                if isinstance(step, dict):
                    claim = step.get("claim") or step.get("text")
                    excerpt = str(step.get("evidence") or "")
                    evidence_type = str(step.get("evidence_type") or "reported_unclassified")
                    relation = str(step.get("relation") or chain.get("relation") or "leads_to")
                    polarity = str(step.get("polarity") or chain.get("polarity") or "")
                    modality = str(step.get("modality") or chain.get("modality") or "")
                    source_location = step.get("source_location") if isinstance(step.get("source_location"), dict) else chain.get("trigger_location")
                else:
                    claim = step
                    excerpt = ""
                    evidence_type = "reported_unclassified"
                    relation = str(chain.get("relation") or "leads_to")
                    polarity = str(chain.get("polarity") or "")
                    modality = str(chain.get("modality") or "")
                    source_location = chain.get("trigger_location")
                step_id = add_node(claim, "intermediate_process", citation)
                if add_edge(
                    prior_id,
                    step_id,
                    relation,
                    citation,
                    excerpt,
                    evidence_type,
                    polarity=polarity,
                    modality=modality,
                    source_location=source_location if isinstance(source_location, dict) else None,
                    confidence=chain.get("confidence"),
                    context=edge_context,
                    interventions=list(raw_interventions) if isinstance(raw_interventions, list) else [],
                    paper_id=paper_id,
                    sub_hypothesis_id=sub_hypothesis_id,
                    source_evidence=bind_record_source_unit(
                        record,
                        excerpt or claim,
                        source_location if isinstance(source_location, dict) else None,
                    ),
                ):
                    edge_indexes.append(len(edges) - 1)
                prior_id = step_id or prior_id
            outcome_id = add_node(chain.get("outcome"), "macro_outcome", citation)
            if add_edge(
                prior_id,
                outcome_id,
                str(chain.get("outcome_relation") or chain.get("relation") or "leads_to"),
                citation,
                str(chain.get("outcome_evidence") or ""),
                "reported_unclassified",
                polarity=str(chain.get("polarity") or ""),
                modality=str(chain.get("modality") or ""),
                source_location=chain.get("outcome_location") if isinstance(chain.get("outcome_location"), dict) else None,
                confidence=chain.get("confidence"),
                context=edge_context,
                interventions=list(raw_interventions) if isinstance(raw_interventions, list) else [],
                paper_id=paper_id,
                sub_hypothesis_id=sub_hypothesis_id,
                source_evidence=bind_record_source_unit(
                    record,
                    str(chain.get("outcome_evidence") or chain.get("outcome") or ""),
                    chain.get("outcome_location") if isinstance(chain.get("outcome_location"), dict) else None,
                ),
            ):
                edge_indexes.append(len(edges) - 1)
            for observable in raw_observables if isinstance(raw_observables, list) else []:
                observable_id = add_node(observable, "observable_signal", citation)
                add_edge(
                    outcome_id, observable_id, "observed_by", citation, "", "observational",
                    context=edge_context, paper_id=paper_id, sub_hypothesis_id=sub_hypothesis_id,
                )
            for intervention in raw_interventions if isinstance(raw_interventions, list) else []:
                intervention_id = add_node(intervention, "external_intervention", citation)
                add_edge(
                    intervention_id, trigger_id, "intervenes_on", citation, "", "experimental",
                    context=edge_context, paper_id=paper_id, sub_hypothesis_id=sub_hypothesis_id,
                )
            chains.append(
                {
                    "chain_id": str(chain.get("chain_id") or f"{record.get('paper_id', 'paper')}_chain_{len(chains) + 1}"),
                    "paper_id": str(record.get("paper_id") or ""),
                    "sub_hypothesis_id": str(record.get("retrieval_branch") or ""),
                    "citation": citation,
                    "trigger": str(chain.get("trigger") or ""),
                    "steps": raw_steps if isinstance(raw_steps, list) else [],
                    "outcome": str(chain.get("outcome") or ""),
                    "observables": list(raw_observables) if isinstance(raw_observables, list) else [],
                    "interventions": list(raw_interventions) if isinstance(raw_interventions, list) else [],
                    "edge_indexes": edge_indexes,
                    "relation": str(chain.get("relation") or "leads_to"),
                    "polarity": str(chain.get("polarity") or ""),
                    "modality": str(chain.get("modality") or ""),
                    "direct_relation": bool(chain.get("direct_relation")),
                    "evidence_edges": list(chain.get("evidence_edges") or []),
                    "context": edge_context,
                    "source_evidence_units": [
                        dict(edges[index].get("source_evidence") or {})
                        for index in edge_indexes
                        if 0 <= index < len(edges)
                        and isinstance(edges[index].get("source_evidence"), dict)
                        and edges[index].get("source_evidence", {}).get("paper_id")
                        and edges[index].get("source_evidence", {}).get("source_unit_id")
                    ],
                }
            )
    supported_paths = causal_supported_paths(edges, nodes)
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "chains": chains,
        "supported_paths": supported_paths,
        "non_causal_claims": non_causal_claims,
    }


def canonical_causal_node_key(value: str) -> str:
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


def causal_supported_paths(edges: list[dict[str, Any]], nodes: dict[str, dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    by_source: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or not edge.get("source") or not edge.get("target"):
            continue
        by_source[str(edge["source"])].append((index, edge))
    node_by_id = {str(item.get("id") or ""): item for item in nodes.values() if isinstance(item, dict)}
    paths: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for first_index, first in enumerate(edges):
        if not isinstance(first, dict):
            continue
        for second_index, second in by_source.get(str(first.get("target") or ""), []):
            key = (first_index, second_index)
            if key in seen or first_index == second_index:
                continue
            seen.add(key)
            paths.append(
                {
                    "path_id": f"path_{len(paths) + 1}",
                    "source": node_by_id.get(str(first.get("source") or ""), {}).get("label", ""),
                    "intermediate": node_by_id.get(str(first.get("target") or ""), {}).get("label", ""),
                    "target": node_by_id.get(str(second.get("target") or ""), {}).get("label", ""),
                    "edge_indexes": [first_index, second_index],
                    "supporting_references": sorted({str(first.get("citation") or ""), str(second.get("citation") or "")} - {""}),
                    "status": "shared_node_evidence_path_not_transitive_claim",
                }
            )
            if len(paths) >= limit:
                return paths
    return paths


def build_coverage_matrix(project_id: str) -> str:
    try:
        from ._project import load_project, save_project
        from ._utils import normalize_label
    except ImportError:
        from _project import load_project, save_project
        from _utils import normalize_label
    project = load_project(project_id)
    matrix: dict[str, dict[str, list[str]]] = {}
    for evidence in project.get("evidence", []):
        method = normalize_label(evidence.get("method", "unknown"))
        scenario = normalize_label(evidence.get("scenario", "unknown"))
        citation = str(evidence.get("citation", ""))
        matrix.setdefault(method, {}).setdefault(scenario, [])
        if citation and citation not in matrix[method][scenario]:
            matrix[method][scenario].append(citation)
    project["coverage_matrix"] = matrix
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "coverage_matrix_built", project_id=project_id, methods=len(matrix))
    return json.dumps(matrix, ensure_ascii=False, indent=2)

def detect_reasoning_gaps(project: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
    except ImportError:
        from _pipeline import project_records_for_mapping
    gaps: list[dict[str, Any]] = []
    records = [record for record in project_records_for_mapping(project) if isinstance(record, dict)]
    gaps.extend(detect_contradiction_gaps(project, records, limit=max(1, limit // 2)))
    if len(gaps) < limit:
        gaps.extend(detect_anomaly_gaps(project, records, limit=limit - len(gaps)))
    return dedupe_knowledge_gaps(gaps)[:limit]


def build_composite_evidence_contract(
    contract_type: str,
    source_units: list[dict[str, Any]],
    *,
    scientific_contract: dict[str, Any],
    required_checks: dict[str, bool],
) -> dict[str, Any]:
    """Build a source-independence-aware contract for a composite gap.

    Source units, papers, and experiments are deliberately counted
    separately.  Two excerpts from one experiment can establish a within-study
    mediation *seed*, but they cannot masquerade as two independent studies.
    """
    deduped_units: dict[str, dict[str, Any]] = {}
    for item in source_units:
        if not isinstance(item, dict) or not item.get("paper_id") or not item.get("source_unit_id"):
            continue
        deduped_units.setdefault(str(item.get("source_unit_id")), dict(item))
    units = list(deduped_units.values())
    distinct_papers = {str(item.get("paper_id") or "") for item in units} - {""}
    experiment_ids = {
        str(
            item.get("experiment_id")
            or item.get("study_id")
            or item.get("trial_id")
            or item.get("dataset_id")
            or item.get("cohort_id")
            or item.get("simulation_id")
            or f"paper:{item.get('paper_id')}"
        )
        for item in units
    } - {""}
    verified = all(item.get("binding_status") == "SOURCE_UNIT_VERIFIED" for item in units)

    def evidence_lane(item: dict[str, Any]) -> str:
        declared = str(
            item.get("evidence_lane") or item.get("evidence_kind")
            or item.get("paper_genre") or item.get("study_design_role") or ""
        ).lower()
        excerpt = str(item.get("excerpt") or "").lower()
        if any(marker in declared for marker in ("experimental", "experiment", "observation", "observational")):
            return "EXPERIMENT_OR_OBSERVATION"
        if any(marker in declared for marker in ("theory", "theoretical", "computational", "simulation")):
            return "THEORY_OR_MODEL"
        text = f"{declared} {excerpt}"
        if any(marker in text for marker in (
            "observation", "observed", "experimental", "experiment", "measurement", "measured",
            "cohort", "field study", "survey", "telescope", "microscopy", "assay",
        )):
            return "EXPERIMENT_OR_OBSERVATION"
        if any(marker in text for marker in (
            "theory", "theoretical", "prediction", "formal", "simulation", "computational", "model",
        )):
            return "THEORY_OR_MODEL"
        return "UNRESOLVED"

    lanes = [evidence_lane(item) for item in units]
    theory_count = sum(lane == "THEORY_OR_MODEL" for lane in lanes)
    observation_count = sum(lane == "EXPERIMENT_OR_OBSERVATION" for lane in lanes)
    if len(distinct_papers) >= 2 and len(experiment_ids) >= 2:
        independence = "INDEPENDENT_CROSS_PAPER_EXPERIMENTS"
    elif len(distinct_papers) >= 2:
        independence = "CROSS_PAPER_SHARED_EXPERIMENT"
    elif len(units) >= 2 and len(distinct_papers) == 1:
        independence = "WITHIN_STUDY_DISTINCT_SOURCE_UNITS"
    else:
        independence = "DUPLICATED_OR_SINGLE_SOURCE_UNIT"

    normalized_type = str(contract_type or "").upper()
    base_checks = {str(key): bool(value) for key, value in required_checks.items()}
    policy_checks: dict[str, bool]
    verification_only = False
    if normalized_type in {"CONTRADICTION", "TABI_CONTRADICTION"}:
        policy_checks = {
            "two_independent_papers": len(distinct_papers) >= 2,
            "two_independent_experiments": len(experiment_ids) >= 2,
        }
    elif normalized_type == "THEORY_OBSERVATION_MISMATCH":
        policy_checks = {
            "theory_or_model_source_present": theory_count >= 1,
            "experiment_or_observation_source_present": observation_count >= 1,
            "distinct_source_units": len(units) >= 2,
            "cross_study_independence": len(distinct_papers) >= 2 and len(experiment_ids) >= 2,
        }
        verification_only = all(value for key, value in policy_checks.items() if key != "cross_study_independence") and not policy_checks["cross_study_independence"]
    elif normalized_type in {"CAUSAL_MEDIATION", "TABI_CAUSAL_COMPOSITION"}:
        policy_checks = {
            "distinct_source_units": len(units) >= 2,
            "cross_study_independence": len(distinct_papers) >= 2 and len(experiment_ids) >= 2,
        }
        verification_only = policy_checks["distinct_source_units"] and not policy_checks["cross_study_independence"]
    elif normalized_type == "EXPLICIT_AUTHOR_STATED_GAP":
        policy_checks = {"explicit_gap_predicate_source_unit": len(units) >= 1}
        verification_only = True
    else:
        policy_checks = {
            "two_independent_papers": len(distinct_papers) >= 2,
            "two_independent_experiments": len(experiment_ids) >= 2,
        }
    checks = {
        "all_source_units_paper_qualified": bool(units) and verified,
        **base_checks,
        **policy_checks,
    }
    scientific_checks_pass = bool(scientific_contract and checks.get("all_source_units_paper_qualified") and all(base_checks.values()))
    primary_independence_passes = bool(scientific_checks_pass and all(policy_checks.values()) and not verification_only)
    gap_seed_valid = bool(scientific_checks_pass and (all(policy_checks.values()) or verification_only))
    if primary_independence_passes:
        status = "PASSED"
    elif gap_seed_valid and normalized_type == "EXPLICIT_AUTHOR_STATED_GAP":
        status = "GAP_SEED_CONFIRMED"
    elif gap_seed_valid and verification_only:
        status = "GAP_EXISTENCE_VERIFICATION_REQUIRED"
    else:
        status = "NOT_PASSED"
    return {
        "version": "composite_gap_evidence_contract_v2",
        "contract_type": normalized_type,
        "status": status,
        "passes": primary_independence_passes,
        "gap_seed_valid": gap_seed_valid,
        "primary_independence_passes": primary_independence_passes,
        "checks": checks,
        "distinct_source_unit_count": len(units),
        "distinct_paper_count": len(distinct_papers),
        "distinct_experiment_count": len(experiment_ids),
        "evidence_independence": independence,
        "evidence_lane_counts": {
            "theory_or_model": theory_count,
            "experiment_or_observation": observation_count,
            "unresolved": sum(lane == "UNRESOLVED" for lane in lanes),
        },
        "allowed_scope": (
            "PRIMARY_COMPOSITE_GAP"
            if primary_independence_passes
            else "GAP_EXISTENCE_VERIFICATION_ONLY"
            if status in {"GAP_EXISTENCE_VERIFICATION_REQUIRED", "GAP_SEED_CONFIRMED"}
            else "REJECTED_COMPOSITE_EVIDENCE"
        ),
        "paper_ids": sorted(distinct_papers),
        "experiment_ids": sorted(experiment_ids),
        "source_unit_ids": [str(item.get("source_unit_id") or "") for item in units],
        "scientific_contract": dict(scientific_contract or {}),
        "failure_reasons": [key for key, value in checks.items() if not value],
    }

def detect_contradiction_gaps(project: dict[str, Any], records: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    try:
        from ._utils import trim_text, unique_preserve_order
    except ImportError:
        from _utils import trim_text, unique_preserve_order
    gaps: list[dict[str, Any]] = []
    comparable = [record for record in records if record_claim_text(record)]
    for index, left in enumerate(comparable):
        for right in comparable[index + 1 :]:
            relation = contradiction_relation(left, right)
            if not relation.get("contradiction"):
                continue
            refs = unique_preserve_order([record_reference(left), record_reference(right)])
            gap = make_gap(
                gap_type="contradiction",
                description=(
                    "Potential conclusion conflict: "
                    f"{relation.get('shared_context')} contains opposing claims: "
                    f"{trim_text(relation.get('left_claim', ''), 180)} vs "
                    f"{trim_text(relation.get('right_claim', ''), 180)}."
                ),
                supporting_references=refs,
                suggested_research_path=(
                    "Extract the exact claim sentences, verify citation contexts/full text, then design a discriminating experiment, "
                    "simulation, benchmark, or theoretical derivation that can separate the competing explanations."
                ),
                value_argument=(
                    "Contradiction gaps are high-value because resolving them can update mechanism understanding, "
                    "not merely fill a sparse method-scenario cell."
                ),
            )
            assessed = assess_gap_dict(project, gap)
            assessed["reasoning_signal"] = {
                "type": "claim_contradiction",
                "shared_context": relation.get("shared_context"),
                "left_polarity": relation.get("left_polarity"),
                "right_polarity": relation.get("right_polarity"),
                "comparability_contract": relation.get("comparability_contract"),
            }
            assessed["competing_mechanisms"] = [
                str(relation.get("left_claim") or ""),
                str(relation.get("right_claim") or ""),
            ]
            assessed["sub_hypothesis_id"] = str(relation.get("sub_hypothesis_id") or "")
            left_source = bind_record_source_unit(left, relation.get("left_claim"), {})
            right_source = bind_record_source_unit(right, relation.get("right_claim"), {})
            assessed["source_evidence_units"] = [left_source, right_source]
            comparability = relation.get("comparability_contract") if isinstance(relation.get("comparability_contract"), dict) else {}
            assessed["composite_evidence_contract"] = build_composite_evidence_contract(
                "CONTRADICTION",
                assessed["source_evidence_units"],
                scientific_contract=comparability,
                required_checks={
                    "same_sub_hypothesis": comparability.get("same_sub_hypothesis") is True,
                    "matched_input_outcome_object": all(
                        bool(item.get("matched"))
                        for item in (comparability.get("dimensions") or {}).values()
                        if isinstance(item, dict)
                    ) and len(comparability.get("dimensions") or {}) == 3,
                    "matched_system_sample_or_regime": bool(
                        ((comparability.get("context_constraints") or {}).get("matched_dimensions") or [])
                    ),
                    "incompatible_claims": bool(relation.get("incompatibility_basis")),
                },
            )
            assessed["gap_epistemic_audit"] = {
                "passes": assessed["composite_evidence_contract"].get("status") == "PASSED",
                "category": "matched_context_opposing_claims",
                "verdict": "COMPOSITE_CONTRADICTION_CANDIDATE",
            }
            assessed["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
            # Score only after the source-qualified composite contract exists.
            assessed = assess_gap_dict(project, assessed)
            gaps.append(assessed)
            if len(gaps) >= limit:
                return gaps
    return gaps

_ANOMALY_TASK_LABEL_PATTERN = re.compile(
    r"\b(?:anomal(?:y|ies)|outlier)\s+(?:detection|detector|classification|segmentation|localization|"
    r"recognition|score|scoring|benchmark|dataset|task|module|head|algorithm|model)\b",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_ANOMALY_MARKERS = (
    "unexplained", "not explained", "cannot explain", "does not explain", "fails to explain",
    "discrepancy", "inconsistent with", "inconsistency", "tension", "mismatch",
    "deviates from", "unexpectedly", "puzzle",
)
_POSITIVE_PERFORMANCE_MARKERS = (
    "high accuracy", "higher accuracy", "best performance", "state-of-the-art", "outperform",
    "improved performance", "strong performance", "few-shot", "zero-shot", "robust performance",
)


def scientific_anomaly_statement_assessment(text: Any) -> dict[str, Any]:
    """Require an epistemic anomaly statement, not an ML/task-name substring."""

    try:
        from ._utils import split_sentences
    except ImportError:
        from _utils import split_sentences
    task_labels: list[str] = []
    for sentence in split_sentences(str(text or "")):
        labels = [match.group(0) for match in _ANOMALY_TASK_LABEL_PATTERN.finditer(sentence)]
        task_labels.extend(labels)
        semantic_remainder = _ANOMALY_TASK_LABEL_PATTERN.sub(" ", sentence)
        lowered = semantic_remainder.lower()
        predicate = explicit_gap_predicate_assessment(semantic_remainder)
        standalone_anomaly = bool(re.search(r"\b(?:anomal(?:y|ies)|anomalous)\b", lowered))
        marker_hits = [marker for marker in _SCIENTIFIC_ANOMALY_MARKERS if marker in lowered]
        if predicate.get("passes") and (standalone_anomaly or marker_hits):
            return {
                "passes": True,
                "sentence": sentence,
                "semantic_remainder": re.sub(r"\s+", " ", semantic_remainder).strip(),
                "task_labels_ignored": task_labels,
                "anomaly_markers": marker_hits + (["standalone_anomaly"] if standalone_anomaly else []),
                "gap_predicate": predicate,
                "verdict": "SCIENTIFIC_ANOMALY_STATEMENT",
            }
    return {
        "passes": False,
        "sentence": "",
        "semantic_remainder": "",
        "task_labels_ignored": task_labels,
        "anomaly_markers": [],
        "gap_predicate": explicit_gap_predicate_assessment(""),
        "verdict": (
            "TASK_LABEL_NOT_SCIENTIFIC_ANOMALY"
            if task_labels else "NO_SOURCE_STATED_UNEXPLAINED_ANOMALY"
        ),
    }


def anomaly_research_path(sentence: str) -> tuple[str, str]:
    lowered = str(sentence or "").lower()
    if any(marker in lowered for marker in _POSITIVE_PERFORMANCE_MARKERS):
        return (
            "EXPLANATORY_MECHANISM_AND_FAILURE_BOUNDARY",
            "First reproduce the reported performance independently; then compare mechanistic explanations and map the conditions, data regimes, or perturbations under which the advantage disappears or reverses.",
        )
    return (
        "MECHANISM_OR_BOUNDARY_DISCRIMINATION",
        "Independently reproduce the reported discrepancy, formulate competing mechanistic explanations, and test which assumption or boundary condition makes the discrepancy appear or disappear.",
    )


def detect_anomaly_gaps(project: dict[str, Any], records: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    gaps: list[dict[str, Any]] = []
    # A direct theory--observation mismatch is a two-fragment comparison, not
    # a paper containing the words "model" and "observed".  Build those
    # composite candidates first.
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            relation = theory_observation_mismatch_relation(left, right)
            if not relation.get("mismatch"):
                continue
            theory = relation["theory_record"]
            observation = relation["observation_record"]
            theory_claim = str(relation.get("theory_claim") or "")
            observation_claim = str(relation.get("observation_claim") or "")
            gap = make_gap(
                gap_type="theory_observation_mismatch",
                description=(
                    "Theory--observation mismatch under matched conditions: "
                    f"{trim_text(theory_claim, 180)} vs {trim_text(observation_claim, 180)}."
                ),
                supporting_references=[record_reference(theory), record_reference(observation)],
                suggested_research_path=(
                    "Evaluate the theory and observation under the same input, object, outcome definition, scale, and regime; "
                    "then test which model assumption or measurement interpretation accounts for the incompatible result."
                ),
                value_argument="A matched prediction--observation discrepancy can falsify or bound a scientific model.",
            )
            assessed = assess_gap_dict(project, gap)
            assessed["sub_hypothesis_id"] = str(relation.get("sub_hypothesis_id") or "")
            assessed["reasoning_signal"] = {
                "type": "theory_observation_mismatch",
                "comparison_contract": relation.get("comparison_contract"),
                "incompatibility_basis": relation.get("incompatibility_basis"),
            }
            assessed["competing_mechanisms"] = [theory_claim, observation_claim]
            assessed["source_evidence_units"] = [
                bind_record_source_unit(theory, theory_claim, {}),
                bind_record_source_unit(observation, observation_claim, {}),
            ]
            comparison = relation.get("comparison_contract") if isinstance(relation.get("comparison_contract"), dict) else {}
            assessed["composite_evidence_contract"] = build_composite_evidence_contract(
                "THEORY_OBSERVATION_MISMATCH",
                assessed["source_evidence_units"],
                scientific_contract=comparison,
                required_checks={
                    "same_sub_hypothesis": comparison.get("same_sub_hypothesis") is True,
                    "matched_input_outcome_object": all(
                        bool(item.get("matched"))
                        for item in (comparison.get("dimensions") or {}).values()
                        if isinstance(item, dict)
                    ) and len(comparison.get("dimensions") or {}) == 3,
                    "matched_system_sample_or_regime": bool(
                        ((comparison.get("context_constraints") or {}).get("matched_dimensions") or [])
                    ),
                    "incompatible_prediction_and_observation": bool(relation.get("incompatibility_basis")),
                },
            )
            assessed["gap_epistemic_audit"] = {
                "passes": assessed["composite_evidence_contract"].get("status") == "PASSED",
                "category": "matched_theory_prediction_and_observation",
                "verdict": "THEORY_OBSERVATION_MISMATCH_CANDIDATE",
            }
            assessed["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
            # Score only after both independent source units and the mismatch
            # contract are attached; generated prose must not establish a gap.
            assessed = assess_gap_dict(project, assessed)
            gaps.append(assessed)
            if len(gaps) >= limit:
                return gaps
    for record in records:
        text = record_claim_text(record)
        anomaly_statement = scientific_anomaly_statement_assessment(text)
        if anomaly_statement.get("passes") is not True:
            continue
        sentence = str(anomaly_statement.get("sentence") or "")
        resolution_target, research_path = anomaly_research_path(sentence)
        gap = make_gap(
            gap_type="anomaly",
            description=f"Source-reported unexplained observation requiring independent corroboration: {sentence}",
            supporting_references=[record_reference(record)],
            suggested_research_path=research_path,
            value_argument=(
                "Any value belongs to independently explaining or bounding the reported observation; the originating paper's performance claim is not itself the value of a research gap."
            ),
        )
        source_unit = bind_record_source_unit(record, sentence, {})
        gap["reasoning_signal"] = {
            "type": "author_stated_unexplained_observation",
            "source_field": record_field(record),
            "source_text": sentence,
            "task_labels_ignored": list(anomaly_statement.get("task_labels_ignored") or []),
            "anomaly_markers": list(anomaly_statement.get("anomaly_markers") or []),
            "resolution_target": resolution_target,
        }
        gap["source_evidence_units"] = [source_unit]
        gap["anomaly_evidence_sufficiency"] = {
            "version": "anomaly_evidence_sufficiency_v1",
            "status": "ORIGINATING_REPORT_ONLY",
            "source_paper_count": 1,
            "independent_corroboration_count": 0,
            "requires_independent_corroboration": True,
            "established_scientific_gap": False,
            "allowed_route": SECONDARY_RESEARCH_OPPORTUNITY_POOL,
            "reason": (
                "One originating paper can state an unexplained observation, but cannot independently establish that the effect is reproducible, anomalous, or still unresolved."
            ),
        }
        gap["gap_epistemic_audit"] = {
            "passes": True,
            "category": "author_stated_anomaly_requires_corroboration",
            "verdict": "AUTHOR_STATED_ANOMALY_REQUIRES_CORROBORATION",
            "explicit_predicate_assessment": dict(anomaly_statement.get("gap_predicate") or {}),
        }
        gap["gap_candidate_pool"] = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        assessed = assess_gap_dict(project, gap)
        gaps.append(assessed)
        if len(gaps) >= limit:
            return gaps
    return gaps

def contradiction_relation(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import normalize_label, trim_text
    except ImportError:
        from _utils import normalize_label, trim_text
    left_text = record_claim_text(left)
    right_text = record_claim_text(right)
    if not left_text or not right_text:
        return {"contradiction": False}
    dimensions = {
        "input_or_intervention": comparable_record_dimension(
            left, right, ("intervention", "independent_variable", "method")
        ),
        "outcome": comparable_record_dimension(
            left, right, ("outcome", "dependent_variable", "benchmark")
        ),
        "research_object": comparable_record_dimension(
            left, right, ("research_object", "subject", "object", "scenario")
        ),
    }
    left_branch = normalized_subhypothesis_id(left.get("retrieval_branch") or left.get("sub_hypothesis_id"))
    right_branch = normalized_subhypothesis_id(right.get("retrieval_branch") or right.get("sub_hypothesis_id"))
    branch_match = bool(left_branch and right_branch and left_branch == right_branch)
    branch_conflict = bool(left_branch and right_branch and left_branch != right_branch)
    context_constraints = contradiction_context_constraints(left, right)
    # A contradiction is meaningful only inside one scientific branch and a
    # positively matched system/sample/regime.  Missing context is not
    # evidence of compatibility: otherwise two claims about different scales
    # could become a false contradiction merely because extraction left both
    # context fields blank.
    if (
        branch_conflict
        or not branch_match
        or context_constraints.get("conflicting_dimensions")
        or not context_constraints.get("matched_dimensions")
        or not all(item.get("matched") for item in dimensions.values())
    ):
        return {"contradiction": False}
    left_polarity = claim_polarity(left_text)
    right_polarity = claim_polarity(right_text)
    numeric_incompatibility = incompatible_numeric_intervals(left_text, right_text)
    polarity_incompatibility = bool(
        left_polarity != "neutral" and right_polarity != "neutral" and left_polarity != right_polarity
    )
    if not polarity_incompatibility and not numeric_incompatibility.get("incompatible"):
        return {"contradiction": False}
    return {
        "contradiction": True,
        "sub_hypothesis_id": left_branch,
        "shared_context": "; ".join(
            str(item.get("left_value") or "") for item in dimensions.values() if item.get("left_value")
        ),
        "left_claim": first_polar_sentence(left_text, left_polarity) or trim_text(left_text, 220),
        "right_claim": first_polar_sentence(right_text, right_polarity) or trim_text(right_text, 220),
        "left_polarity": left_polarity,
        "right_polarity": right_polarity,
        "incompatibility_basis": (
            "opposite_claim_polarity" if polarity_incompatibility else "non_overlapping_numeric_intervals"
        ),
        "numeric_interval_comparison": numeric_incompatibility,
        "comparability_contract": {
            "dimensions": dimensions,
            "same_sub_hypothesis": branch_match,
            "sub_hypothesis_undetermined": not left_branch or not right_branch,
            "context_constraints": context_constraints,
            "passes": True,
            "rule": "same input/intervention + outcome + object/context, with opposing claim direction",
        },
    }


def _claim_numeric_intervals(text: str) -> list[dict[str, Any]]:
    """Extract only explicit intervals/uncertainties; isolated numbers do not conflict."""
    intervals: list[dict[str, Any]] = []
    unit_pattern = r"(%|K|°C|Pa|kPa|MPa|GPa|Hz|s|ms|ns|m|nm|eV|J|W|mol(?:/L)?|[A-Za-z][A-Za-z0-9/_^-]{0,12})"
    patterns = (
        re.compile(rf"(?P<center>-?\d+(?:\.\d+)?)\s*(?:±|\+/-)\s*(?P<error>\d+(?:\.\d+)?)\s*(?P<unit>{unit_pattern})", re.IGNORECASE),
        re.compile(rf"(?:\[|\()?\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:,|to|–|—|-)\s*(?P<high>-?\d+(?:\.\d+)?)\s*(?:\]|\))?\s*(?P<unit>{unit_pattern})", re.IGNORECASE),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            if groups.get("center") is not None:
                center = float(groups["center"])
                error = abs(float(groups["error"]))
                low, high = center - error, center + error
            else:
                low, high = sorted((float(groups["low"]), float(groups["high"])))
            intervals.append({
                "low": low,
                "high": high,
                "unit": str(groups.get("unit") or "").lower(),
                "source_text": match.group(0),
            })
    return intervals


def incompatible_numeric_intervals(left_text: str, right_text: str) -> dict[str, Any]:
    left_intervals = _claim_numeric_intervals(left_text)
    right_intervals = _claim_numeric_intervals(right_text)
    for left in left_intervals:
        for right in right_intervals:
            if left["unit"] != right["unit"]:
                continue
            if float(left["high"]) < float(right["low"]) or float(right["high"]) < float(left["low"]):
                return {"incompatible": True, "left": left, "right": right}
    return {"incompatible": False, "left_intervals": left_intervals, "right_intervals": right_intervals}


def _record_comparison_signature(record: dict[str, Any]) -> dict[str, str]:
    chains = [item for item in (record.get("causal_chains") or []) if isinstance(item, dict)]
    first_chain = chains[0] if chains else {}
    context = record.get("causal_context") if isinstance(record.get("causal_context"), dict) else {}
    return {
        "input": str(
            record.get("intervention") or record.get("independent_variable") or record.get("condition")
            or first_chain.get("trigger") or ""
        ).strip(),
        "outcome": str(
            record.get("outcome") or record.get("dependent_variable") or record.get("benchmark")
            or first_chain.get("outcome") or ""
        ).strip(),
        "research_object": str(
            record.get("research_object") or record.get("subject") or record.get("object")
            or context.get("research_object") or ""
        ).strip(),
        "sub_hypothesis_id": normalized_subhypothesis_id(
            record.get("retrieval_branch") or record.get("sub_hypothesis_id")
            or (record.get("alignment_assessment") or {}).get("sub_hypothesis_id")
        ),
    }


def theory_observation_mismatch_relation(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    theory_markers = ("theory", "theoretical", "model predicts", "simulation predicts", "calculated", "predicted")
    observation_markers = ("observed", "measured", "observation", "experimental data", "telescope", "survey data")
    left_text, right_text = record_claim_text(left), record_claim_text(right)
    orientations = ((left, right, left_text, right_text), (right, left, right_text, left_text))
    for theory, observation, theory_text, observation_text in orientations:
        if not any(marker in theory_text.lower() for marker in theory_markers):
            continue
        if not any(marker in observation_text.lower() for marker in observation_markers):
            continue
        theory_sig = _record_comparison_signature(theory)
        observation_sig = _record_comparison_signature(observation)
        dimensions = {
            key: comparable_record_dimension(
                {"value": theory_sig[key]}, {"value": observation_sig[key]}, ("value",)
            )
            for key in ("input", "outcome", "research_object")
        }
        same_branch = bool(
            theory_sig["sub_hypothesis_id"]
            and theory_sig["sub_hypothesis_id"] == observation_sig["sub_hypothesis_id"]
        )
        context = contradiction_context_constraints(theory, observation)
        left_polarity, right_polarity = claim_polarity(theory_text), claim_polarity(observation_text)
        polarity_conflict = bool(
            left_polarity != "neutral" and right_polarity != "neutral" and left_polarity != right_polarity
        )
        numeric_conflict = incompatible_numeric_intervals(theory_text, observation_text)
        comparison_passes = bool(
            same_branch
            and all(item.get("matched") for item in dimensions.values())
            and not context.get("conflicting_dimensions")
            and context.get("matched_dimensions")
            and (polarity_conflict or numeric_conflict.get("incompatible"))
        )
        if not comparison_passes:
            continue
        return {
            "mismatch": True,
            "theory_record": theory,
            "observation_record": observation,
            "theory_claim": theory_text,
            "observation_claim": observation_text,
            "sub_hypothesis_id": theory_sig["sub_hypothesis_id"],
            "incompatibility_basis": "opposite_claim_polarity" if polarity_conflict else "non_overlapping_numeric_intervals",
            "comparison_contract": {
                "passes": True,
                "same_sub_hypothesis": same_branch,
                "dimensions": dimensions,
                "context_constraints": context,
                "numeric_interval_comparison": numeric_conflict,
            },
        }
    return {"mismatch": False}


def contradiction_context_constraints(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reject boundary-condition differences masquerading as contradictions."""
    field_groups = {
        "species_or_system": ("species", "organism", "system"),
        "model_or_sample": ("cell_model", "model_system", "sample", "cohort"),
        "stage_or_regime": ("developmental_stage", "stage", "operating_regime", "condition"),
        "timepoint": ("timepoint", "time_point", "measurement_time", "duration"),
        "scale": ("scale", "spatial_scale", "temporal_scale", "resolution"),
    }
    matched: list[str] = []
    unknown: list[str] = []
    conflicts: list[str] = []
    values: dict[str, dict[str, str]] = {}
    for dimension, fields in field_groups.items():
        left_value = next((str(left.get(field) or "").strip() for field in fields if str(left.get(field) or "").strip()), "")
        right_value = next((str(right.get(field) or "").strip() for field in fields if str(right.get(field) or "").strip()), "")
        values[dimension] = {"left": left_value, "right": right_value}
        if not left_value or not right_value:
            unknown.append(dimension)
            continue
        result = comparable_record_dimension(
            {"value": left_value}, {"value": right_value}, ("value",)
        )
        if result.get("matched"):
            matched.append(dimension)
        else:
            conflicts.append(dimension)
    return {
        "matched_dimensions": matched,
        "unknown_dimensions": unknown,
        "conflicting_dimensions": conflicts,
        "values": values,
        "status": "COMPATIBLE" if not conflicts else "BOUNDARY_CONDITION_MISMATCH",
    }


def comparable_record_dimension(
    left: dict[str, Any],
    right: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    try:
        from ._utils import normalize_label
    except ImportError:
        from _utils import normalize_label
    left_value = next((str(left.get(field) or "").strip() for field in fields if str(left.get(field) or "").strip()), "")
    right_value = next((str(right.get(field) or "").strip() for field in fields if str(right.get(field) or "").strip()), "")
    if not left_value or not right_value:
        return {"matched": False, "status": "UNDERDETERMINED", "left_value": left_value, "right_value": right_value}
    left_normal = normalize_label(left_value)
    right_normal = normalize_label(right_value)
    score = text_jaccard(left_normal, right_normal)
    matched = bool(
        score >= 0.55
        or (left_normal and left_normal in right_normal)
        or (right_normal and right_normal in left_normal)
    )
    return {
        "matched": matched,
        "status": "MATCHED" if matched else "INCOMPATIBLE",
        "left_value": left_value,
        "right_value": right_value,
        "similarity": round(score, 3),
    }

def record_claim_text(record: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space, scalar
    except ImportError:
        from _utils import normalize_space, scalar
    return normalize_space(
        " ".join(
            scalar(record.get(key))
            for key in ("conclusion", "contribution", "limitation", "abstract", "strengths", "improvements")
            if scalar(record.get(key))
        )
    )

def record_reference(record: dict[str, Any]) -> str:
    return str(record.get("citation") or record.get("title") or record.get("paper_id") or "")


_AGGREGATION_OPPOSING_MARKERS = (
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
    "adverse_or_reversal_evidence",
)

_AGGREGATION_BOUNDARY_MARKERS = (
    "boundary",
    "generalization",
    "generalisation",
    "heterogeneity",
    "moderator",
    "threshold",
    "transportability",
    "external validity",
    "boundary_or_generalization",
    "boundary_or_negative_evidence",
)


def _normalize_subhypothesis_id_for_aggregation(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\bSH\s*[-_:]?\s*(\d+)\b", text, flags=re.IGNORECASE)
    if match:
        return f"SH{int(match.group(1))}"
    return text.split(":", 1)[0].strip()


def _record_subhypothesis_ids_for_aggregation(record: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    def add(value: Any) -> None:
        normalized = _normalize_subhypothesis_id_for_aggregation(value)
        if normalized and normalized not in ids:
            ids.append(normalized)

    bindings = record.get("subhypothesis_bindings")
    for binding in bindings if isinstance(bindings, list) else []:
        if isinstance(binding, dict):
            add(binding.get("sub_hypothesis_id"))
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    retrieval_scope = context.get("retrieval_scope") if isinstance(context.get("retrieval_scope"), dict) else {}
    for value in (
        record.get("sub_hypothesis_id"),
        record.get("retrieval_branch"),
        alignment.get("sub_hypothesis_id"),
        context.get("sub_hypothesis_id"),
        retrieval_scope.get("sub_hypothesis_id"),
        context.get("query_branch"),
        context.get("primary_query_branch"),
    ):
        add(value)
    return ids


def _record_excluded_from_sh_gap_synthesis(record: dict[str, Any]) -> bool:
    """Return True for project-background records that must not seed SH gaps."""

    if not isinstance(record, dict):
        return True
    alignment = (
        record.get("alignment_assessment")
        if isinstance(record.get("alignment_assessment"), dict)
        else {}
    )
    context = (
        record.get("import_context")
        if isinstance(record.get("import_context"), dict)
        else {}
    )
    scopes = {
        str(record.get("admission_scope") or "").strip().lower(),
        str(record.get("sh_locality_scope") or "").strip().lower(),
        str(alignment.get("admission_scope") or "").strip().lower(),
        str(alignment.get("sh_locality_scope") or "").strip().lower(),
        str(context.get("admission_scope") or "").strip().lower(),
        str(context.get("sh_locality_scope") or "").strip().lower(),
    }
    if "project_background_only" in scopes:
        return True
    if (
        record.get("project_background_only") is True
        or record.get("excluded_from_sh_gap_synthesis") is True
        or alignment.get("project_background_only") is True
        or alignment.get("excluded_from_sh_gap_synthesis") is True
        or context.get("project_background_only") is True
        or context.get("excluded_from_sh_gap_synthesis") is True
    ):
        return True
    if str(record.get("next_use") or alignment.get("next_use") or context.get("next_use") or "").strip().lower() == "project_context_only":
        return True
    bindings = record.get("subhypothesis_bindings")
    for binding in bindings if isinstance(bindings, list) else []:
        if not isinstance(binding, dict):
            continue
        binding_scope = str(
            binding.get("admission_scope")
            or binding.get("sh_locality_scope")
            or ""
        ).strip().lower()
        if (
            binding_scope == "project_background_only"
            or binding.get("project_background_only") is True
            or binding.get("excluded_from_sh_gap_synthesis") is True
            or str(binding.get("next_use") or "").strip().lower() == "project_context_only"
        ):
            return True
    return False


def visual_evidence_for_gap_synthesis(
    record: dict[str, Any],
    sub_hypothesis_id: str,
) -> list[dict[str, Any]]:
    """Return candidate-only visual notes for SH gap synthesis.

    Visual evidence is deliberately kept out of supporting references and source
    evidence units.  It can only surface as a human-review note.
    """

    if not isinstance(record, dict):
        return []
    sub_id = _normalize_subhypothesis_id_for_aggregation(sub_hypothesis_id)
    notes: list[dict[str, Any]] = []
    for visual in record.get("visual_evidence") or []:
        if not isinstance(visual, dict):
            continue
        visual_sub_id = _normalize_subhypothesis_id_for_aggregation(
            visual.get("sub_hypothesis_id")
        )
        if visual_sub_id and sub_id and visual_sub_id != sub_id:
            continue
        if visual.get("excluded_from_sh_gap_synthesis") is True:
            continue
        scope = str(
            visual.get("admission_scope")
            or visual.get("evidence_role")
            or ""
        )
        if scope not in {
            "visual_sh_local_auxiliary",
            "visual_component_bridge_candidate",
            "visual_core_candidate_pending_review",
        }:
            continue
        notes.append(
            {
                "paper_id": str(
                    visual.get("paper_id") or record.get("paper_id") or ""
                ),
                "visual_id": str(visual.get("visual_id") or ""),
                "sub_hypothesis_id": visual_sub_id or sub_id,
                "admission_scope": scope,
                "source_locator": str(visual.get("source_locator") or ""),
                "page": visual.get("page"),
                "caption": str(visual.get("caption") or "")[:300],
                "claim": str(visual.get("rationale") or "")[:500],
                "requires_human_review": True,
                "counts_toward_gate": False,
                "excluded_from_direct_core_gate": True,
                "source_pdf_url": str(
                    visual.get("source_pdf_url")
                    or record.get("open_access_pdf")
                    or ""
                ),
            }
        )
    return notes


def _record_claim_polarity_for_aggregation(record: dict[str, Any]) -> str:
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    type_evidence = alignment.get("type_directed_evidence") if isinstance(alignment.get("type_directed_evidence"), dict) else {}
    bindings = record.get("subhypothesis_bindings") if isinstance(record.get("subhypothesis_bindings"), list) else []
    binding = next((item for item in bindings if isinstance(item, dict)), {})
    explicit = str(
        record.get("evidence_polarity")
        or alignment.get("evidence_polarity")
        or binding.get("evidence_polarity")
        or context.get("evidence_path_polarity")
        or alignment.get("evidence_path_polarity")
        or binding.get("evidence_path_polarity")
        or ""
    ).strip().lower()
    if explicit in {"supportive", "opposing", "mixed", "boundary", "unclear"}:
        return explicit
    text = " ".join(
        str(value or "")
        for value in (
            record.get("evidence_path_role"),
            alignment.get("evidence_path_role"),
            binding.get("evidence_path_role"),
            context.get("evidence_path_role"),
            context.get("retrieval_layer_role"),
            context.get("target_lane"),
            alignment.get("evidence_lane"),
            type_evidence.get("evidence_lane"),
            context.get("negative_evidence_interpretation"),
            alignment.get("causal_role"),
        )
    ).lower()
    if "mixed" in text:
        return "mixed"
    if any(marker in text for marker in _AGGREGATION_OPPOSING_MARKERS):
        return "opposing"
    if any(marker in text for marker in _AGGREGATION_BOUNDARY_MARKERS):
        return "boundary"
    if bool(alignment.get("core_eligible") or alignment.get("import_eligible")):
        return "supportive"
    return "unclear"


def _record_is_core_for_aggregation(record: dict[str, Any]) -> bool:
    full_text = record.get("full_text_acquisition") if isinstance(record.get("full_text_acquisition"), dict) else {}
    if full_text and full_text.get("available") is False:
        return False
    structuring = record.get("fulltext_structuring") if isinstance(record.get("fulltext_structuring"), dict) else {}
    if structuring and structuring.get("eligible_for_evidence_admission") is False:
        return False
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    if alignment.get("core_eligible") is True or alignment.get("standard_core_eligible") is True:
        return True
    if record.get("core_eligible") is True or record.get("standard_core_eligible") is True:
        return True
    bindings = record.get("subhypothesis_bindings") if isinstance(record.get("subhypothesis_bindings"), list) else []
    return any(
        isinstance(binding, dict)
        and (
            binding.get("core_evidence_capable") is True
            or str(binding.get("evidence_path_role") or "").lower() in {
                "core_validation",
                "causal_validation",
                "predictive_validation",
                "adverse_or_reversal",
            }
        )
        for binding in bindings
    )


def _record_counts_as_related_fulltext_for_aggregation(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    layer = str(record.get("layer") or record.get("retrieval_layer") or "").lower()
    if "preprint" in layer:
        return False
    full_text = (
        record.get("full_text_acquisition")
        if isinstance(record.get("full_text_acquisition"), dict)
        else {}
    )
    structuring = (
        record.get("fulltext_structuring")
        if isinstance(record.get("fulltext_structuring"), dict)
        else {}
    )
    if full_text and full_text.get("available") is False:
        return False
    if structuring and structuring.get("eligible_for_evidence_admission") is False:
        return False
    fulltext_usable = bool(
        record.get("fulltext_structurally_usable")
        or record.get("fulltext_evidence_admissible")
        or full_text.get("available")
        or record.get("full_text_excerpt")
    )
    if not fulltext_usable:
        return False
    alignment = (
        record.get("alignment_assessment")
        if isinstance(record.get("alignment_assessment"), dict)
        else {}
    )
    return bool(
        record.get("corpus_admitted") is True
        or alignment.get("corpus_admitted") is True
        or _record_is_core_for_aggregation(record)
    )


def _aggregation_record_identity(record: dict[str, Any]) -> str:
    text = str(
        record.get("paper_id")
        or record.get("doi")
        or record.get("openalex_id")
        or record.get("semantic_scholar_id")
        or record.get("title")
        or ""
    ).strip()
    if text:
        return text
    return sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _aggregation_record_node(
    record: dict[str, Any],
    *,
    node_type: str,
    polarity: str,
    sub_hypothesis_id: str,
) -> dict[str, Any]:
    return {
        "node_type": node_type,
        "paper_id": str(record.get("paper_id") or ""),
        "sub_hypothesis_id": sub_hypothesis_id,
        "title": str(record.get("title") or "")[:220],
        "citation": record_reference(record),
        "evidence_polarity": polarity,
        "evidence_path_role": str(record.get("evidence_path_role") or ""),
        "supports_primary_claim": bool(record.get("supports_primary_claim")),
        "weakens_primary_claim": bool(record.get("weakens_primary_claim")),
        "boundary_condition_supported": bool(record.get("boundary_condition_supported")),
    }


def _noncore_pool_name_for_aggregation(record: dict[str, Any]) -> str:
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    role_text = " ".join(
        str(value or "")
        for value in (
            record.get("evidence_role"),
            record.get("evidence_path_role"),
            alignment.get("evidence_role"),
            alignment.get("evidence_path_role"),
            alignment.get("evidence_lane"),
            record.get("corpus_admission_reason"),
            alignment.get("corpus_admission_reason"),
        )
    ).lower()
    polarity = str(record.get("evidence_polarity") or alignment.get("evidence_polarity") or "").lower()
    if "adverse" in role_text or "reversal" in role_text or polarity == "opposing":
        return "adverse_context"
    if "boundary" in role_text or "generalization" in role_text or polarity == "boundary":
        return "boundary_context"
    if "foundation" in role_text or "foundational" in role_text:
        return "related_foundation"
    if "component" in role_text or "mechanism" in role_text:
        return "component_mechanism"
    if "platform" in role_text:
        return "platform_context"
    if "method" in role_text:
        return "method_context"
    return "method_context"


def _aggregation_axis_pass(alignment: dict[str, Any], *keys: str) -> bool:
    return any(
        isinstance(alignment.get(key), dict)
        and alignment.get(key, {}).get("passes") is True
        for key in keys
    )


def _noncore_missing_axes_for_aggregation(record: dict[str, Any]) -> list[str]:
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    return type_directed_missing_axes(record, alignment)


def _noncore_pool_item_for_aggregation(record: dict[str, Any], sub_hypothesis_id: str) -> dict[str, Any]:
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    full_text = record.get("full_text_acquisition") if isinstance(record.get("full_text_acquisition"), dict) else {}
    fulltext_usable = bool(
        record.get("fulltext_structurally_usable")
        or record.get("fulltext_evidence_admissible")
        or full_text.get("available")
    )
    return {
        "paper_id": str(record.get("paper_id") or ""),
        "sub_hypothesis_id": sub_hypothesis_id,
        "title": str(record.get("title") or "")[:220],
        "citation": record_reference(record),
        "evidence_role": str(record.get("evidence_role") or alignment.get("evidence_role") or ""),
        "evidence_polarity": str(record.get("evidence_polarity") or alignment.get("evidence_polarity") or "unclear"),
        "corpus_admission_reason": str(record.get("corpus_admission_reason") or alignment.get("corpus_admission_reason") or ""),
        "alignment_verdict": str(alignment.get("verdict") or ""),
        "missing_contract_requirements": _noncore_missing_axes_for_aggregation(record),
        "full_text_available": fulltext_usable,
        "fulltext_structurally_usable": fulltext_usable,
        "auxiliary_material_only": not fulltext_usable,
        "counts_toward_fulltext_gate": fulltext_usable,
        "claim_strength_effect": (
            "no_claim_strength_increase"
            if not fulltext_usable
            else str(record.get("claim_strength_effect") or "")
        ),
    }


def _status_from_aggregation_counts(counts: dict[str, int]) -> EvidencePathStatus:
    supportive = int(counts.get("supportive_core") or 0)
    opposing = int(counts.get("opposing_core") or 0)
    boundary = int(counts.get("boundary_core") or 0)
    mixed = int(counts.get("mixed_core") or 0)
    any_core = supportive + opposing + boundary + mixed + int(counts.get("unclear_core") or 0)
    if mixed or (supportive and opposing):
        core_effect = "mixed"
    elif supportive:
        core_effect = "supported"
    elif opposing:
        core_effect = "unsupported"
    elif any_core:
        core_effect = "mixed"
    else:
        core_effect = "untested"
    adverse_reversal = "found" if opposing or mixed else "not_found" if any_core else "untested"
    if boundary >= 2:
        boundary_generalization = "defined"
    elif boundary == 1:
        boundary_generalization = "partial"
    elif supportive or opposing or mixed:
        boundary_generalization = "missing"
    else:
        boundary_generalization = "untested"
    conflicts: list[str] = []
    if supportive and (opposing or mixed):
        conflicts.append("core_vs_adverse")
    if supportive and boundary_generalization in {"missing", "partial"}:
        conflicts.append("core_vs_boundary")
    if (opposing or mixed) and boundary_generalization in {"missing", "partial"}:
        conflicts.append("adverse_vs_boundary")
    return EvidencePathStatus(
        core_effect=core_effect,
        adverse_reversal=adverse_reversal,
        boundary_generalization=boundary_generalization,
        conflict_taxonomy=conflicts,
    )


def build_papergraph_evidence_aggregation(project: dict[str, Any]) -> dict[str, Any]:
    """Aggregate full-text papergraph evidence into core/adverse/boundary SH states."""

    records = project.get("papergraph") if isinstance(project.get("papergraph"), list) else []
    subhypotheses = project.get("sub_hypotheses") if isinstance(project.get("sub_hypotheses"), list) else []

    def object_maturity_metadata(item: dict[str, Any]) -> dict[str, Any]:
        audit = (
            item.get("object_maturity_preflight")
            if isinstance(item.get("object_maturity_preflight"), dict)
            else item.get("object_maturity_audit")
            if isinstance(item.get("object_maturity_audit"), dict)
            else {}
        )
        status = str(
            item.get("object_maturity_status")
            or audit.get("object_status")
            or audit.get("status")
            or ""
        ).strip().lower()
        retrieval_mode = str(
            item.get("object_maturity_retrieval_mode")
            or audit.get("retrieval_mode")
            or ""
        ).strip().lower()
        direct_core_allowed = not (
            item.get("direct_core_evidence_allowed") is False
            or audit.get("direct_core_evidence_allowed") is False
            or retrieval_mode == "component_bridge_boundary"
            or status in {
                "component_evidence_only",
                "translational_bridge",
                "speculative_unanchored",
            }
        )
        retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), dict) else {}
        coverage = (
            retrieval.get("cumulative_full_text_coverage")
            if isinstance(retrieval.get("cumulative_full_text_coverage"), dict)
            else {}
        )
        corpus_related_fulltext = int(
            coverage.get("imported_related_full_text_count")
            if coverage.get("imported_related_full_text_count") is not None
            else coverage.get("corpus_related_full_text_count")
            if coverage.get("corpus_related_full_text_count") is not None
            else retrieval.get("corpus_related_full_text_records")
            or 0
        )
        coverage_noncore_total = int(
            coverage.get("noncore_evidence_total")
            if coverage.get("noncore_evidence_total") is not None
            else 0
        )
        corpus_related_fulltext_target = max(
            1,
            int(
                coverage.get("imported_related_full_text_target")
                or coverage.get("corpus_related_full_text_target")
                or coverage.get("imported_full_text_target")
                or coverage.get("peer_reviewed_full_text_target")
                or 10
            ),
        )
        return {
            "object_maturity_status": status,
            "object_maturity_retrieval_mode": retrieval_mode,
            "direct_core_evidence_allowed": direct_core_allowed,
            "direct_core_disallowed_by_object_maturity": not direct_core_allowed,
            "corpus_related_fulltext": corpus_related_fulltext,
            "corpus_related_fulltext_target": corpus_related_fulltext_target,
            "coverage_noncore_evidence_total": coverage_noncore_total,
        }

    sh_index: dict[str, dict[str, Any]] = {}
    for item in subhypotheses:
        if not isinstance(item, dict):
            continue
        sh_id = _normalize_subhypothesis_id_for_aggregation(item.get("id"))
        if sh_id:
            sh_index.setdefault(
                sh_id,
                {
                    "sub_hypothesis_id": sh_id,
                    "focus": str(item.get("focus") or item.get("hypothesis") or "")[:400],
                    "scientific_object": str(item.get("scientific_object") or "")[:240],
                    **object_maturity_metadata(item),
                },
            )
    buckets: dict[str, dict[str, Any]] = {
        sh_id: {
            **meta,
            "supportive_core": 0,
            "opposing_core": 0,
            "boundary_core": 0,
            "mixed_core": 0,
            "unclear_core": 0,
            "supportive_references": [],
            "opposing_references": [],
            "boundary_references": [],
            "mixed_references": [],
            "evidence_nodes": [],
            "conflict_edges": [],
            "visual_evidence_notes": [],
            "noncore_evidence_pool": {
                "method_context": [],
                "platform_context": [],
                "component_mechanism": [],
                "related_foundation": [],
                "boundary_context": [],
                "adverse_context": [],
            },
        }
        for sh_id, meta in sh_index.items()
    }

    excluded_from_gap_synthesis_total = 0
    for record in records:
        if not isinstance(record, dict) or record.get("active", True) is False:
            continue
        if _record_excluded_from_sh_gap_synthesis(record):
            excluded_from_gap_synthesis_total += 1
            continue
        sh_ids = _record_subhypothesis_ids_for_aggregation(record)
        visual_bound_sh_ids = [
            _normalize_subhypothesis_id_for_aggregation(visual.get("sub_hypothesis_id"))
            for visual in (record.get("visual_evidence") or [])
            if isinstance(visual, dict)
        ]
        for visual_sh_id in visual_bound_sh_ids:
            if visual_sh_id and visual_sh_id not in sh_ids:
                sh_ids.append(visual_sh_id)
        for sh_id in sh_ids:
            visual_notes = visual_evidence_for_gap_synthesis(record, sh_id)
            if not visual_notes:
                continue
            bucket = buckets.setdefault(
                sh_id,
                {
                    "sub_hypothesis_id": sh_id,
                    "focus": "",
                    "scientific_object": "",
                    "supportive_core": 0,
                    "opposing_core": 0,
                    "boundary_core": 0,
                    "mixed_core": 0,
                    "unclear_core": 0,
                    "supportive_references": [],
                    "opposing_references": [],
                    "boundary_references": [],
                    "mixed_references": [],
                    "evidence_nodes": [],
                    "conflict_edges": [],
                    "visual_evidence_notes": [],
                    "noncore_evidence_pool": {
                        "method_context": [],
                        "platform_context": [],
                        "component_mechanism": [],
                        "related_foundation": [],
                        "boundary_context": [],
                        "adverse_context": [],
                    },
                },
            )
            bucket.setdefault("visual_evidence_notes", [])
            existing_visual_keys = {
                (
                    str(note.get("paper_id") or ""),
                    str(note.get("visual_id") or ""),
                    str(note.get("source_locator") or ""),
                )
                for note in bucket.get("visual_evidence_notes") or []
                if isinstance(note, dict)
            }
            for note in visual_notes:
                key = (
                    str(note.get("paper_id") or ""),
                    str(note.get("visual_id") or ""),
                    str(note.get("source_locator") or ""),
                )
                if key in existing_visual_keys:
                    continue
                if len(bucket["visual_evidence_notes"]) >= 24:
                    break
                bucket["visual_evidence_notes"].append(note)
                existing_visual_keys.add(key)
        if sh_ids and _record_counts_as_related_fulltext_for_aggregation(record):
            identity = _aggregation_record_identity(record)
            for sh_id in sh_ids:
                bucket = buckets.setdefault(
                    sh_id,
                    {
                        "sub_hypothesis_id": sh_id,
                        "focus": "",
                        "scientific_object": "",
                        "supportive_core": 0,
                        "opposing_core": 0,
                        "boundary_core": 0,
                        "mixed_core": 0,
                        "unclear_core": 0,
                        "supportive_references": [],
                        "opposing_references": [],
                        "boundary_references": [],
                        "mixed_references": [],
                        "evidence_nodes": [],
                        "conflict_edges": [],
                        "visual_evidence_notes": [],
                        "noncore_evidence_pool": {
                            "method_context": [],
                            "platform_context": [],
                            "component_mechanism": [],
                            "related_foundation": [],
                            "boundary_context": [],
                            "adverse_context": [],
                        },
                    },
                )
                bucket.setdefault("_corpus_related_fulltext_record_identities", set()).add(identity)
        if (
            record.get("corpus_admitted") is True
            and not _record_is_core_for_aggregation(record)
            and sh_ids
        ):
            pool_name = _noncore_pool_name_for_aggregation(record)
            for sh_id in sh_ids:
                bucket = buckets.setdefault(
                    sh_id,
                    {
                        "sub_hypothesis_id": sh_id,
                        "focus": "",
                        "scientific_object": "",
                        "supportive_core": 0,
                        "opposing_core": 0,
                        "boundary_core": 0,
                        "mixed_core": 0,
                        "unclear_core": 0,
                        "supportive_references": [],
                        "opposing_references": [],
                        "boundary_references": [],
                        "mixed_references": [],
                        "evidence_nodes": [],
                        "conflict_edges": [],
                        "visual_evidence_notes": [],
                        "noncore_evidence_pool": {
                            "method_context": [],
                            "platform_context": [],
                            "component_mechanism": [],
                            "related_foundation": [],
                            "boundary_context": [],
                            "adverse_context": [],
                        },
                    },
                )
                pool = bucket.setdefault("noncore_evidence_pool", {})
                pool.setdefault(pool_name, [])
                if len(pool[pool_name]) < 16:
                    pool[pool_name].append(
                        _noncore_pool_item_for_aggregation(record, sh_id)
                    )
        if not _record_is_core_for_aggregation(record):
            continue
        polarity = _record_claim_polarity_for_aggregation(record)
        if not sh_ids:
            continue
        reference = record_reference(record)
        for sh_id in sh_ids:
            bucket = buckets.setdefault(
                sh_id,
                {
                    "sub_hypothesis_id": sh_id,
                    "focus": "",
                    "scientific_object": "",
                    "supportive_core": 0,
                    "opposing_core": 0,
                    "boundary_core": 0,
                    "mixed_core": 0,
                    "unclear_core": 0,
                    "supportive_references": [],
                    "opposing_references": [],
                    "boundary_references": [],
                    "mixed_references": [],
                "evidence_nodes": [],
                "conflict_edges": [],
                "visual_evidence_notes": [],
                "noncore_evidence_pool": {
                    "method_context": [],
                    "platform_context": [],
                        "component_mechanism": [],
                        "related_foundation": [],
                        "boundary_context": [],
                        "adverse_context": [],
                    },
                },
            )
            if polarity == "opposing":
                bucket["opposing_core"] += 1
                if reference and reference not in bucket["opposing_references"]:
                    bucket["opposing_references"].append(reference)
                bucket["evidence_nodes"].append(
                    _aggregation_record_node(record, node_type="ADVERSE_EFFECT", polarity=polarity, sub_hypothesis_id=sh_id)
                )
            elif polarity == "boundary":
                bucket["boundary_core"] += 1
                if reference and reference not in bucket["boundary_references"]:
                    bucket["boundary_references"].append(reference)
                bucket["evidence_nodes"].append(
                    _aggregation_record_node(record, node_type="BOUNDARY_CONDITION", polarity=polarity, sub_hypothesis_id=sh_id)
                )
            elif polarity == "mixed":
                bucket["mixed_core"] += 1
                if reference and reference not in bucket["mixed_references"]:
                    bucket["mixed_references"].append(reference)
                bucket["evidence_nodes"].append(
                    _aggregation_record_node(record, node_type="CORE_EFFECT", polarity=polarity, sub_hypothesis_id=sh_id)
                )
                bucket["evidence_nodes"].append(
                    _aggregation_record_node(record, node_type="ADVERSE_EFFECT", polarity=polarity, sub_hypothesis_id=sh_id)
                )
            elif polarity == "supportive":
                bucket["supportive_core"] += 1
                if reference and reference not in bucket["supportive_references"]:
                    bucket["supportive_references"].append(reference)
                bucket["evidence_nodes"].append(
                    _aggregation_record_node(record, node_type="CORE_EFFECT", polarity=polarity, sub_hypothesis_id=sh_id)
                )
            else:
                bucket["unclear_core"] += 1

    for sh_id, bucket in buckets.items():
        status = _status_from_aggregation_counts(bucket)
        bucket["path_status"] = asdict(status)
        related_fulltext_from_records = len(
            bucket.get("_corpus_related_fulltext_record_identities")
            if isinstance(bucket.get("_corpus_related_fulltext_record_identities"), set)
            else set()
        )
        bucket["corpus_related_fulltext_from_records"] = related_fulltext_from_records
        bucket["corpus_related_fulltext"] = max(
            int(bucket.get("corpus_related_fulltext") or 0),
            related_fulltext_from_records,
        )
        bucket.pop("_corpus_related_fulltext_record_identities", None)
        noncore_pool = bucket.get("noncore_evidence_pool") if isinstance(bucket.get("noncore_evidence_pool"), dict) else {}
        bucket["noncore_evidence_pool_counts"] = {
            key: len(value)
            for key, value in sorted(noncore_pool.items())
            if isinstance(value, list)
        }
        bucket["noncore_evidence_total"] = sum(
            int(value) for value in bucket["noncore_evidence_pool_counts"].values()
        )
        visual_notes = [
            item
            for item in bucket.get("visual_evidence_notes") or []
            if isinstance(item, dict)
        ]
        bucket["visual_evidence_notes"] = visual_notes[:24]
        bucket["visual_evidence_count"] = len(bucket["visual_evidence_notes"])
        bucket["visual_evidence_gate_policy"] = "candidate_only_until_human_review"
        bucket["noncore_missing_contract_requirement_counts"] = dict(sorted(Counter(
            axis
            for items in noncore_pool.values()
            if isinstance(items, list)
            for item in items
            if isinstance(item, dict)
            for axis in (item.get("missing_contract_requirements") or [])
        ).items()))
        node_counts = Counter(str(node.get("node_type") or "") for node in bucket.get("evidence_nodes") or [])
        if "core_vs_adverse" in status.conflict_taxonomy:
            bucket["conflict_edges"].append(
                {
                    "node_type": "CONFLICT_EDGE",
                    "source": "CORE_EFFECT",
                    "target": "ADVERSE_EFFECT",
                    "conflict_type": "core_vs_adverse",
                    "sub_hypothesis_id": sh_id,
                }
            )
            node_counts["CONFLICT_EDGE"] += 1
        bucket["node_counts"] = dict(sorted(node_counts.items()))
        bucket["claim_strength_modifier"] = {
            "supportive_core": int(bucket.get("supportive_core") or 0),
            "opposing_core": int(bucket.get("opposing_core") or 0),
            "boundary_core": int(bucket.get("boundary_core") or 0),
            "mixed_core": int(bucket.get("mixed_core") or 0),
            "verdict": (
                "mixed_or_condition_dependent"
                if status.core_effect == "mixed" or status.conflict_taxonomy
                else "primarily_opposing_or_reversal"
                if status.core_effect == "unsupported"
                else "conditional_or_boundary_limited"
                if status.boundary_generalization in {"defined", "partial"} and status.core_effect == "supported"
                else "supportive"
                if status.core_effect == "supported"
                else "insufficient_core_direction"
            ),
        }

    return {
        "schema_version": "papergraph_evidence_aggregation_v1",
        "node_types": ["CORE_EFFECT", "ADVERSE_EFFECT", "BOUNDARY_CONDITION", "CONFLICT_EDGE"],
        "subhypotheses": buckets,
        "summary": {
            "subhypothesis_count": len(buckets),
            "conflict_subhypothesis_count": sum(
                1 for item in buckets.values()
                if item.get("path_status", {}).get("conflict_taxonomy")
            ),
            "opposing_core_total": sum(int(item.get("opposing_core") or 0) for item in buckets.values()),
            "boundary_core_total": sum(int(item.get("boundary_core") or 0) for item in buckets.values()),
            "noncore_evidence_total": sum(int(item.get("noncore_evidence_total") or 0) for item in buckets.values()),
            "visual_evidence_note_total": sum(int(item.get("visual_evidence_count") or 0) for item in buckets.values()),
            "excluded_from_sh_gap_synthesis_total": excluded_from_gap_synthesis_total,
        },
    }


def _subhypothesis_focus_lookup(project: dict[str, Any]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for item in project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []:
        if not isinstance(item, dict):
            continue
        sh_id = _normalize_subhypothesis_id_for_aggregation(item.get("id"))
        if not sh_id:
            continue
        audit = (
            item.get("object_maturity_preflight")
            if isinstance(item.get("object_maturity_preflight"), dict)
            else item.get("object_maturity_audit")
            if isinstance(item.get("object_maturity_audit"), dict)
            else {}
        )
        status = str(
            item.get("object_maturity_status")
            or audit.get("object_status")
            or audit.get("status")
            or ""
        ).strip().lower()
        retrieval_mode = str(
            item.get("object_maturity_retrieval_mode")
            or audit.get("retrieval_mode")
            or ""
        ).strip().lower()
        direct_core_allowed = not (
            item.get("direct_core_evidence_allowed") is False
            or audit.get("direct_core_evidence_allowed") is False
            or retrieval_mode == "component_bridge_boundary"
            or status in {
                "component_evidence_only",
                "translational_bridge",
                "speculative_unanchored",
            }
        )
        lookup[sh_id] = {
            "focus": str(item.get("focus") or item.get("hypothesis") or sh_id).strip(),
            "scientific_object": str(item.get("scientific_object") or "").strip(),
            "comparison": str(item.get("comparison") or item.get("baseline_or_comparator") or "").strip(),
            "falsification_condition": str(item.get("falsification_condition") or "").strip(),
            "object_maturity_status": status,
            "object_maturity_retrieval_mode": retrieval_mode,
            "direct_core_evidence_allowed": direct_core_allowed,
        }
    return lookup


def synthesize_conflict_boundary_gap_text(
    *,
    sub_hypothesis_id: str,
    focus: str,
    scientific_object: str,
    status: dict[str, Any],
) -> tuple[str, str, str]:
    object_phrase = scientific_object or focus or sub_hypothesis_id
    core_state = str(status.get("core_effect") or "untested")
    adverse_state = str(status.get("adverse_reversal") or "untested")
    boundary_state = str(status.get("boundary_generalization") or "untested")
    if core_state in {"supported", "mixed"} and adverse_state == "found" and boundary_state == "missing":
        return (
            "conflict_boundary_gap",
            (
                f"The unresolved gap in {sub_hypothesis_id} is not whether '{object_phrase}' has a reported core effect; "
                "the current corpus contains both core-effect and adverse/reversal evidence. The scientific gap is "
                "which comparison, implementation, population, material, system, or operating-boundary conditions determine "
                "when the core effect is not offset, reversed, or burden-shifted by the adverse pathway."
            ),
            (
                "Estimate the boundary threshold with a design that jointly measures the expected effect, the adverse/reversal "
                "mechanism, and the relevant baseline or comparator across heterogeneous conditions."
            ),
        )
    if core_state in {"supported", "mixed"} and adverse_state == "found" and boundary_state == "partial":
        return (
            "conflict_boundary_gap",
            (
                f"{sub_hypothesis_id} has both supportive and adverse/reversal core evidence for '{object_phrase}', but boundary "
                "evidence is only partial. The gap is to resolve where the effect changes sign, attenuates, or becomes conditional "
                "rather than to add more one-direction supportive studies."
            ),
            (
                "Run a boundary-focused comparison across moderators, implementation settings, or system regimes and report "
                "the sign/size of both beneficial and adverse pathways."
            ),
        )
    if core_state == "unsupported" and adverse_state == "found":
        return (
            "primary_claim_reversal_gap",
            (
                f"The available core evidence for {sub_hypothesis_id} currently points mainly to adverse, null, or reversal "
                f"effects for '{object_phrase}'. The gap is whether the original positive claim can be rescued under narrower "
                "boundary conditions or should be reformulated as a reversal/constraint hypothesis."
            ),
            (
                "Test the primary claim against an explicit baseline while pre-specifying boundary conditions that could explain "
                "why opposing evidence dominates."
            ),
        )
    if core_state == "supported" and boundary_state == "missing":
        return (
            "conflict_boundary_gap",
            (
                f"The core effect in {sub_hypothesis_id} is supported for '{object_phrase}', but boundary/generalization evidence "
                "is missing. The gap is the range of populations, materials, systems, implementation regimes, or comparators over "
                "which the effect remains valid or disappears."
            ),
            (
                "Prioritize external validation, moderator analysis, or stress-condition testing rather than another same-context "
                "positive-effect study."
            ),
        )
    return ("", "", "")


def detect_conflict_boundary_gaps(project: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    aggregation = (
        project.get("papergraph_evidence_aggregation")
        if isinstance(project.get("papergraph_evidence_aggregation"), dict)
        else {}
    )
    if not aggregation:
        aggregation = build_papergraph_evidence_aggregation(project)
        project["papergraph_evidence_aggregation"] = aggregation
        if isinstance(project.get("knowledge_map"), dict):
            project["knowledge_map"]["papergraph_evidence_aggregation"] = aggregation
            project["knowledge_map"]["evidence_aggregation"] = aggregation
    buckets = aggregation.get("subhypotheses") if isinstance(aggregation.get("subhypotheses"), dict) else {}
    focus_lookup = _subhypothesis_focus_lookup(project)
    records_by_id = {
        str(record.get("paper_id") or record.get("doi") or ""): record
        for record in project.get("papergraph", []) if isinstance(record, dict)
    }
    gaps: list[dict[str, Any]] = []
    for sh_id, bucket in buckets.items():
        if len(gaps) >= max(0, int(limit)):
            break
        if not isinstance(bucket, dict):
            continue
        status = bucket.get("path_status") if isinstance(bucket.get("path_status"), dict) else {}
        conflict_taxonomy = list(status.get("conflict_taxonomy") or [])
        core_state = str(status.get("core_effect") or "")
        adverse_state = str(status.get("adverse_reversal") or "")
        boundary_state = str(status.get("boundary_generalization") or "")
        if not (
            conflict_taxonomy
            or (core_state == "supported" and boundary_state == "missing")
            or (core_state == "unsupported" and adverse_state == "found")
        ):
            continue
        focus_meta = focus_lookup.get(str(sh_id), {})
        gap_type, description, research_path = synthesize_conflict_boundary_gap_text(
            sub_hypothesis_id=str(sh_id),
            focus=str(focus_meta.get("focus") or bucket.get("focus") or sh_id),
            scientific_object=str(focus_meta.get("scientific_object") or bucket.get("scientific_object") or ""),
            status=status,
        )
        if not gap_type or not description:
            continue
        references = []
        for key in ("supportive_references", "opposing_references", "boundary_references", "mixed_references"):
            for ref in bucket.get(key, []) if isinstance(bucket.get(key), list) else []:
                if ref and ref not in references:
                    references.append(ref)
        source_units: list[dict[str, Any]] = []
        for node in bucket.get("evidence_nodes", []) if isinstance(bucket.get("evidence_nodes"), list) else []:
            if not isinstance(node, dict):
                continue
            paper_id = str(node.get("paper_id") or "")
            record = records_by_id.get(paper_id, {})
            if not record:
                continue
            excerpt = str(
                record.get("full_text_excerpt")
                or record.get("conclusion")
                or record.get("abstract")
                or record.get("title")
                or ""
            ).strip()
            if not excerpt:
                continue
            role = str(node.get("node_type") or "").lower()
            excerpt_window = excerpt[:1200]
            source_units.append({
                "paper_id": paper_id,
                "source_unit_id": f"{paper_id}:papergraph_evidence_aggregation:{role}",
                "source_field": "papergraph_evidence_aggregation",
                "excerpt": excerpt_window,
                "excerpt_hash": sha256(excerpt_window.encode("utf-8")).hexdigest()[:16],
                "binding_status": "papergraph_evidence_aggregation",
                "evidence_polarity": str(node.get("evidence_polarity") or ""),
                "evidence_node_type": str(node.get("node_type") or ""),
            })
            if len(source_units) >= 8:
                break
        value_argument = (
            "This is a high-value scientific gap because the corpus already contains directional tension: "
            "resolving the boundary can convert a one-sided claim into a conditional, falsifiable mechanism."
        )
        gap = make_gap(
            gap_type=gap_type,
            description=description,
            supporting_references=references,
            suggested_research_path=research_path,
            value_argument=value_argument,
            hypothesis_ingredients={
                "methods": ["conflict-aware evidence synthesis"],
                "scenarios": [str(focus_meta.get("focus") or bucket.get("focus") or sh_id)],
                "benchmarks": [str(focus_meta.get("comparison") or "explicit baseline or comparator")],
                "operating_conditions": ["boundary conditions", "adverse/reversal pathway", "core effect pathway"],
                "measurable_metrics": ["effect size", "sign reversal", "threshold", "net outcome"],
            },
            project_id=str(project.get("id") or project.get("project_id") or ""),
        )
        gap["sub_hypothesis_id"] = str(sh_id)
        gap["evidence_path_status"] = dict(status)
        gap["papergraph_evidence_aggregation"] = {
            "supportive_core": int(bucket.get("supportive_core") or 0),
            "opposing_core": int(bucket.get("opposing_core") or 0),
            "boundary_core": int(bucket.get("boundary_core") or 0),
            "mixed_core": int(bucket.get("mixed_core") or 0),
            "node_counts": dict(bucket.get("node_counts") or {}),
            "conflict_edges": list(bucket.get("conflict_edges") or []),
        }
        gap["gap_epistemic_audit"] = {
            "passes": True,
            "category": "conflict_boundary_evidence_synthesis",
            "verdict": "BOUNDARY_CONDITION_GAP",
            "evidence_path_status": dict(status),
        }
        gap["source_evidence_units"] = source_units
        gap["source_candidate_provenance"] = {
            "paper_ids": [str(item.get("paper_id") or "") for item in source_units],
            "source_unit_ids": [str(item.get("source_unit_id") or "") for item in source_units],
            "provenance_complete": bool(source_units),
            "source": "papergraph_evidence_aggregation",
        }
        gap["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
        mark_restricted_component_bridge_hypothesis_policy(gap)
        gaps.append(assess_gap_dict(project, gap))
    return gaps


def _dominant_noncore_pool(noncore_pool: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for key, value in noncore_pool.items():
        if isinstance(value, list) and value:
            candidates.append((str(key), [item for item in value if isinstance(item, dict)]))
    if not candidates:
        return "", []
    candidates.sort(key=lambda item: (-len(item[1]), item[0]))
    return candidates[0]


_RESTRICTED_BRIDGE_REQUIRED_ROLES = ("input", "mediator", "outcome", "comparison")


def _restricted_bridge_role_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in (
            "value",
            "normalized_value",
            "candidate",
            "text",
            "label",
            "name",
        ):
            text = _restricted_bridge_role_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [_restricted_bridge_role_text(item) for item in value]
        return "; ".join(part for part in parts if part).strip()
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"unresolved", "unknown", "none", "n/a", "generic_placeholder"}:
        return ""
    if lowered.startswith("requires_") or lowered.startswith("requires-"):
        return ""
    if "fragment_refs" in lowered and "'value': ''" in lowered:
        return ""
    if "fragment_refs" in lowered and '"value": ""' in lowered:
        return ""
    return text


def _subhypothesis_for_restricted_bridge(
    project: dict[str, Any],
    sub_hypothesis_id: Any,
) -> dict[str, Any]:
    wanted = _normalize_subhypothesis_id_for_aggregation(sub_hypothesis_id)
    if not wanted:
        return {}
    for item in project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []:
        if not isinstance(item, dict):
            continue
        current = _normalize_subhypothesis_id_for_aggregation(
            item.get("id") or item.get("sub_hypothesis_id")
        )
        if current == wanted:
            return item
    return {}


def _alignment_contract_for_restricted_bridge(
    project: dict[str, Any],
    sub_hypothesis_id: Any,
) -> dict[str, Any]:
    # V2 gap discovery does not use alignment-card causal contracts.  A
    # caller reaching this historical helper is on the old mechanism branch;
    # return no contract rather than reconstructing a causal fallback from an
    # otherwise valid research-question SH.
    if _project_uses_research_question_evidence_v3(project):
        return {}
    branch = _normalize_subhypothesis_id_for_aggregation(sub_hypothesis_id)
    contracts = (
        project.get("subhypothesis_alignment_contracts")
        if isinstance(project.get("subhypothesis_alignment_contracts"), dict)
        else {}
    )
    contract = contracts.get(branch) if isinstance(contracts.get(branch), dict) else {}
    if contract:
        return contract
    sub_hypothesis = _subhypothesis_for_restricted_bridge(project, branch)
    if not sub_hypothesis:
        return {}
    try:
        from ._research_alignment import (
            build_project_alignment_card,
            build_subhypothesis_alignment_contract,
        )
    except ImportError:
        from _research_alignment import (
            build_project_alignment_card,
            build_subhypothesis_alignment_contract,
        )
    contract = build_subhypothesis_alignment_contract(
        project,
        sub_hypothesis,
        build_project_alignment_card(project),
    )
    project.setdefault("subhypothesis_alignment_contracts", {})[branch] = contract
    return contract


def _role_entry(value: Any, *, source: str, source_unit_ids: list[str] | None = None) -> dict[str, Any]:
    text = _restricted_bridge_role_text(value)
    return {
        "value": text,
        "source": source if text else "",
        "fragment_refs": list(source_unit_ids or []) if text else [],
        "restricted_context_only": True,
    }


def _declared_subhypothesis_bridge_role_contract(
    project: dict[str, Any],
    sub_hypothesis_id: Any,
    *,
    source_units: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    branch = _normalize_subhypothesis_id_for_aggregation(sub_hypothesis_id)
    sub_hypothesis = _subhypothesis_for_restricted_bridge(project, branch)
    contract = _alignment_contract_for_restricted_bridge(project, branch)
    causal_contract = (
        contract.get("causal_contract")
        if isinstance(contract.get("causal_contract"), dict)
        else sub_hypothesis.get("causal_contract")
        if isinstance(sub_hypothesis.get("causal_contract"), dict)
        else {}
    )
    chain = [
        _restricted_bridge_role_text(item)
        for item in (
            contract.get("causal_chain")
            if isinstance(contract.get("causal_chain"), list)
            else sub_hypothesis.get("causal_chain")
            if isinstance(sub_hypothesis.get("causal_chain"), list)
            else []
        )
    ]
    chain = [item for item in chain if item]
    dependent_variables = (
        contract.get("dependent_variables")
        if isinstance(contract.get("dependent_variables"), list)
        else sub_hypothesis.get("dependent_variables")
        if isinstance(sub_hypothesis.get("dependent_variables"), list)
        else []
    )
    source_unit_ids = [
        str(unit.get("source_unit_id") or "")
        for unit in (source_units or [])
        if isinstance(unit, dict) and str(unit.get("source_unit_id") or "")
    ]
    mediator_candidates: list[Any] = [
        causal_contract.get("pivotal_mechanism"),
        causal_contract.get("mechanism"),
        contract.get("mechanism"),
        sub_hypothesis.get("mechanism"),
        sub_hypothesis.get("mediator"),
    ]
    mediator_candidates.extend(causal_contract.get("supporting_mediators") or [])
    if len(chain) >= 3:
        mediator_candidates.extend(chain[1:-1])
    roles = {
        "object": _role_entry(
            contract.get("scientific_object")
            or sub_hypothesis.get("scientific_object")
            or contract.get("scientific_object_identity_anchor")
            or sub_hypothesis.get("focus"),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
        "input": _role_entry(
            contract.get("independent_variable")
            or contract.get("focal_variable")
            or sub_hypothesis.get("independent_variable")
            or (chain[0] if len(chain) >= 2 else ""),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
        "mediator": _role_entry(
            next(
                (
                    _restricted_bridge_role_text(value)
                    for value in mediator_candidates
                    if _restricted_bridge_role_text(value)
                ),
                "",
            ),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
        "outcome": _role_entry(
            causal_contract.get("outcome")
            or contract.get("outcome")
            or dependent_variables
            or (chain[-1] if len(chain) >= 2 else ""),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
        "comparison": _role_entry(
            contract.get("baseline_or_comparator")
            or contract.get("comparison")
            or sub_hypothesis.get("baseline_or_comparator")
            or sub_hypothesis.get("comparison")
            or sub_hypothesis.get("control_condition")
            or sub_hypothesis.get("comparison_conditions")
            or sub_hypothesis.get("controls"),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
        "falsification": _role_entry(
            contract.get("falsification_condition")
            or sub_hypothesis.get("falsification_condition"),
            source="declared_subhypothesis_alignment_contract",
            source_unit_ids=source_unit_ids,
        ),
    }
    missing = [
        role
        for role in _RESTRICTED_BRIDGE_REQUIRED_ROLES
        if not _restricted_bridge_role_text(roles.get(role))
    ]
    return {
        "schema_version": "restricted_component_bridge_role_contract_v1",
        "sub_hypothesis_id": branch,
        "status": "READY" if not missing else "REPAIR_REQUIRED",
        "ready": not missing,
        "roles": roles,
        "missing_roles": missing,
        "required_roles": list(_RESTRICTED_BRIDGE_REQUIRED_ROLES),
        "source_unit_ids": source_unit_ids,
        "source": "declared_subhypothesis_alignment_contract",
        "promotion_policy": (
            "This role contract can seed only a restricted component-bridge "
            "hypothesis. It cannot promote component/bridge evidence into a "
            "direct final-object claim."
        ),
    }


def restricted_component_bridge_role_contract_ready(gap: dict[str, Any] | None) -> bool:
    item = gap if isinstance(gap, dict) else {}
    contract = (
        item.get("restricted_bridge_role_contract")
        if isinstance(item.get("restricted_bridge_role_contract"), dict)
        else {}
    )
    roles = contract.get("roles") if isinstance(contract.get("roles"), dict) else {}
    if contract and contract.get("ready") is False:
        return False
    for role in _RESTRICTED_BRIDGE_REQUIRED_ROLES:
        if isinstance(roles.get(role), dict):
            value = roles.get(role)
        elif role == "input":
            value = item.get("input") or item.get("intervention")
        elif role == "mediator":
            value = item.get("mediator") or item.get("proposed_mediator")
        else:
            value = item.get(role)
        if not _restricted_bridge_role_text(value):
            return False
    return True


def _attach_restricted_component_bridge_role_contract(
    gap: dict[str, Any],
    role_contract: dict[str, Any],
) -> dict[str, Any]:
    item = gap if isinstance(gap, dict) else {}
    roles = role_contract.get("roles") if isinstance(role_contract.get("roles"), dict) else {}
    input_value = _restricted_bridge_role_text(roles.get("input"))
    mediator_value = _restricted_bridge_role_text(roles.get("mediator"))
    outcome_value = _restricted_bridge_role_text(roles.get("outcome"))
    comparison_value = _restricted_bridge_role_text(roles.get("comparison"))
    falsification_value = _restricted_bridge_role_text(roles.get("falsification"))
    item["restricted_bridge_role_contract"] = role_contract
    item["component_bridge_context_ready"] = True
    ready = restricted_component_bridge_role_contract_ready(item)
    item["restricted_bridge_role_contract_ready"] = ready
    item["component_bridge_gap_synthesis_ready"] = ready
    if input_value:
        item["input"] = input_value
        item["intervention"] = input_value
    if mediator_value:
        item["mediator"] = mediator_value
        item["proposed_mediator"] = mediator_value
    if outcome_value:
        item["outcome"] = outcome_value
    if comparison_value:
        item["comparison"] = comparison_value
    if falsification_value:
        item["falsification"] = falsification_value
    bundle = dict(item.get("mechanism_evidence_bundle") or {})
    bundle.update({
        "schema_version": "restricted_component_bridge_mechanism_bundle_v1",
        "status": (
            "READY_FOR_RESTRICTED_COMPONENT_BRIDGE_ROLE_CONTRACT"
            if ready else "RESTRICTED_COMPONENT_BRIDGE_ROLE_CONTRACT_INCOMPLETE"
        ),
        "intervention": input_value,
        "mediator": mediator_value,
        "outcome": outcome_value,
        "comparison": comparison_value,
        "falsification": falsification_value,
        "causal_chain": {
            "input": input_value,
            "mediator": mediator_value,
            "outcome": outcome_value,
            "comparison": comparison_value,
            "falsification": falsification_value,
        },
        "causal_field_provenance": {
            role: dict(value)
            for role, value in roles.items()
            if isinstance(value, dict)
        },
        "missing_requirements": [
            f"{role}_role_contract_missing"
            for role in role_contract.get("missing_roles", [])
        ],
        "direct_core_evidence_allowed": False,
        "restricted_component_bridge_gap": True,
    })
    item["mechanism_evidence_bundle"] = bundle
    if ready:
        item["causal_readiness_verdict"] = {
            "version": "causal_readiness_verdict_v1",
            "passes": True,
            "verdict": "COMPONENT_BRIDGE_RESTRICTED_GAP_READY",
            "failure_verdicts": [],
            "research_mode": "COMPONENT_BRIDGE_BOUNDARY_SYNTHESIS",
            "direct_core_evidence_allowed": False,
            "claim_strength_effect": "no_final_object_claim_validation",
            "causal_fields": {
                "input": {"value": input_value, "restricted_context_only": True},
                "mediator": {"value": mediator_value, "restricted_context_only": True},
                "outcome": {"value": outcome_value, "restricted_context_only": True},
                "comparison": {"value": comparison_value, "restricted_context_only": True},
            },
        }
    else:
        missing = list(role_contract.get("missing_roles") or [])
        item["scientific_state"] = "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED"
        item["gap_track"] = "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED"
        item["gap_candidate_pool"] = EVIDENCE_EXTRACTION_SHORTAGE_POOL
        item["eligible_for_hypothesis_generation"] = False
        item["eligible_for_restricted_bridge_hypothesis"] = False
        item["restricted_component_bridge_hypothesis_allowed"] = False
        item["socrates_targeted_retrieval_allowed"] = False
        item["causal_readiness_verdict"] = {
            "version": "causal_readiness_verdict_v1",
            "passes": False,
            "verdict": "COMPONENT_BRIDGE_ROLE_CONTRACT_INCOMPLETE",
            "failure_verdicts": [f"{role.upper()}_INVALID" for role in missing],
            "research_mode": "COMPONENT_BRIDGE_BOUNDARY_SYNTHESIS",
            "direct_core_evidence_allowed": False,
            "claim_strength_effect": "no_final_object_claim_validation",
            "causal_fields": {
                "input": {"value": input_value, "restricted_context_only": True},
                "mediator": {"value": mediator_value, "restricted_context_only": True},
                "outcome": {"value": outcome_value, "restricted_context_only": True},
                "comparison": {"value": comparison_value, "restricted_context_only": True},
            },
        }
        item["hypothesis_readiness"] = {
            **(item.get("hypothesis_readiness") if isinstance(item.get("hypothesis_readiness"), dict) else {}),
            "status": "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED",
            "ready_for_hypothesis_generation": False,
            "restricted_component_bridge": True,
            "missing_roles": missing,
        }
    return item


def _noncore_gap_description(
    *,
    sub_hypothesis_id: str,
    focus: str,
    scientific_object: str,
    pool_name: str,
    missing_axes: dict[str, int],
) -> tuple[str, str]:
    object_phrase = scientific_object or focus or sub_hypothesis_id
    missing = ", ".join(
        key.replace("_", " ")
        for key, _ in sorted(missing_axes.items(), key=lambda item: (-int(item[1] or 0), item[0]))[:3]
    ) or "declared causal edge, endpoint/readout, or comparison"
    if pool_name in {"method_context", "platform_context", "related_foundation"}:
        description = (
            f"{sub_hypothesis_id} has related method/platform or foundational evidence for '{object_phrase}', "
            f"but the current corpus does not establish the SH-specific {missing}. The gap is not absence of literature; "
            "it is the missing causal validation that connects the demonstrated platform or preparation method to the "
            "declared mechanism, endpoint, and comparator."
        )
        research_path = (
            "Design an end-to-end validation study that keeps the demonstrated method/platform in scope, varies the declared "
            "input or preparation parameters, and measures the SH-specific endpoint against the stated baseline/comparator."
        )
        return description, research_path
    if pool_name == "component_mechanism":
        description = (
            f"{sub_hypothesis_id} has component-level mechanism evidence around '{object_phrase}', but lacks integrated "
            f"validation of the full causal chain, especially {missing}. The gap is whether individually plausible components "
            "jointly explain the declared outcome under the intended comparison."
        )
        research_path = (
            "Combine component evidence in a single design that tests the whole input--mediator--outcome path and reports "
            "whether the integrated model or mechanism outperforms the relevant baseline."
        )
        return description, research_path
    if pool_name == "adverse_context":
        description = (
            f"{sub_hypothesis_id} has adverse/reversal context evidence for '{object_phrase}', but lacks a direct test that "
            f"quantifies whether the adverse pathway offsets the intended effect under the declared {missing}."
        )
        research_path = (
            "Measure the intended and adverse pathways in the same study, with explicit thresholds for when the net effect "
            "changes sign or becomes condition-dependent."
        )
        return description, research_path
    if pool_name == "boundary_context":
        description = (
            f"{sub_hypothesis_id} has boundary/generalization context evidence for '{object_phrase}', but the corpus does not "
            f"define the validity frontier for the declared {missing}."
        )
        research_path = (
            "Run boundary-focused validation across moderators, operating regimes, populations, materials, or implementation "
            "settings while preserving the SH-specific endpoint and comparator."
        )
        return description, research_path
    return (
        f"{sub_hypothesis_id} has related non-core evidence for '{object_phrase}', but lacks SH-specific causal validation of {missing}.",
        "Convert the related non-core evidence into a direct test of the declared causal edge, endpoint/readout, and comparator.",
    )


def detect_component_bridge_gap_synthesis_gaps(
    project: dict[str, Any],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Emit restricted gaps for immature-object component/bridge evidence.

    These gaps are intentionally *not* direct validation claims.  They only say
    that a component, translational bridge, or boundary corpus exists while the
    final declared object still lacks direct-core validation.
    """

    aggregation = (
        project.get("papergraph_evidence_aggregation")
        if isinstance(project.get("papergraph_evidence_aggregation"), dict)
        else {}
    )
    if not aggregation:
        aggregation = build_papergraph_evidence_aggregation(project)
        project["papergraph_evidence_aggregation"] = aggregation
    buckets = aggregation.get("subhypotheses") if isinstance(aggregation.get("subhypotheses"), dict) else {}
    focus_lookup = _subhypothesis_focus_lookup(project)
    records_by_id = {
        str(record.get("paper_id") or ""): record
        for record in project.get("papergraph", []) if isinstance(record, dict)
    }
    gaps: list[dict[str, Any]] = []
    for sh_id, bucket in buckets.items():
        if len(gaps) >= max(0, int(limit)):
            break
        if not isinstance(bucket, dict):
            continue
        direct_core_allowed = bool(
            bucket.get("direct_core_evidence_allowed") is not False
        )
        focus_meta = focus_lookup.get(str(sh_id), {})
        if focus_meta.get("direct_core_evidence_allowed") is False:
            direct_core_allowed = False
        if direct_core_allowed:
            continue
        noncore_total = max(
            int(bucket.get("noncore_evidence_total") or 0),
            int(bucket.get("coverage_noncore_evidence_total") or 0),
        )
        corpus_related_total = int(bucket.get("corpus_related_fulltext") or 0)
        corpus_related_target = max(
            1,
            int(bucket.get("corpus_related_fulltext_target") or 10),
        )
        direct_supportive_core_available = bool(
            int(bucket.get("supportive_core") or 0) >= 1
        )
        release_gate_passed = bool(
            corpus_related_total >= corpus_related_target
            or direct_supportive_core_available
        )
        if not release_gate_passed:
            continue
        noncore_pool = bucket.get("noncore_evidence_pool") if isinstance(bucket.get("noncore_evidence_pool"), dict) else {}
        pool_name, pool_items = _dominant_noncore_pool(noncore_pool)
        if not pool_items:
            pool_items = [
                item
                for values in noncore_pool.values()
                if isinstance(values, list)
                for item in values
                if isinstance(item, dict)
            ][:8]
        missing_axes = (
            bucket.get("noncore_missing_contract_requirement_counts")
            if isinstance(bucket.get("noncore_missing_contract_requirement_counts"), dict)
            else {}
        )
        object_phrase = str(
            focus_meta.get("scientific_object")
            or bucket.get("scientific_object")
            or focus_meta.get("focus")
            or bucket.get("focus")
            or sh_id
        )
        description = (
            f"{sh_id} has component, translational-bridge, boundary, or auxiliary evidence for '{object_phrase}', "
            "but the object-maturity audit disallows direct-core claims for the final object. The gap is the missing "
            "direct validation step connecting those component/bridge findings to the final declared object, endpoint, "
            "and comparison."
        )
        research_path = (
            "Use the existing component and bridge corpus only to design a staged validation study: first bind the "
            "component mechanism or bridge model to a concrete endpoint and comparator, then test whether the final "
            "object itself is directly supported. Do not infer that the final object is already validated."
        )
        references: list[str] = []
        source_units: list[dict[str, Any]] = []
        for item in pool_items[:8]:
            ref = str(item.get("citation") or item.get("title") or "")
            if ref and ref not in references:
                references.append(ref)
            paper_id = str(item.get("paper_id") or "")
            record = records_by_id.get(paper_id, {})
            excerpt = str(
                record.get("full_text_excerpt")
                or record.get("abstract")
                or record.get("conclusion")
                or record.get("title")
                or ""
            ).strip()
            if excerpt:
                excerpt_window = excerpt[:1200]
                source_units.append({
                    "paper_id": paper_id,
                    "sub_hypothesis_id": str(sh_id),
                    "source_unit_id": f"{paper_id}:component_bridge_gap_synthesis:{pool_name or 'noncore'}",
                    "source_field": "component_bridge_gap_synthesis",
                    "excerpt": excerpt_window,
                    "excerpt_hash": sha256(excerpt_window.encode("utf-8")).hexdigest()[:16],
                    "binding_status": "SOURCE_UNIT_VERIFIED",
                    "source_role": "component_bridge_context",
                    "evidence_role": str(item.get("evidence_role") or ""),
                    "missing_contract_requirements": list(
                        item.get("missing_contract_requirements") or []
                    ),
                })
        gap = make_gap(
            gap_type="component_bridge_gap_synthesis",
            description=description,
            supporting_references=references,
            suggested_research_path=research_path,
            value_argument=(
                "This gap is valuable because the corpus is not empty, but its evidence status is deliberately limited: "
                "it supports component/bridge reasoning, not validation of the final object."
            ),
            hypothesis_ingredients={
                "methods": ["component bridge synthesis", (pool_name or "noncore context").replace("_", " ")],
                "scenarios": [str(focus_meta.get("focus") or bucket.get("focus") or sh_id)],
                "benchmarks": ["final-object direct-core validation benchmark"],
                "measurement_resources": ["component/bridge/boundary auxiliary or full-text corpus"],
                "measurable_metrics": [
                    axis.replace("_", " ")
                    for axis in list(missing_axes.keys())[:4]
                ] or ["declared final-object endpoint/readout"],
            },
            project_id=str(project.get("id") or project.get("project_id") or ""),
        )
        gap["sub_hypothesis_id"] = str(sh_id)
        gap["component_bridge_context_ready"] = True
        gap["direct_core_evidence_allowed"] = False
        gap["forbidden_claims"] = [
            "Do not state that the final object has been directly validated.",
            "Do not upgrade component, bridge, or boundary evidence into positive final-object claim strength.",
        ]
        gap["claim_strength_effect"] = "no_final_object_claim_validation"
        gap["noncore_evidence_pool_counts"] = dict(bucket.get("noncore_evidence_pool_counts") or {})
        gap["noncore_missing_contract_requirement_counts"] = dict(missing_axes)
        gap["papergraph_evidence_aggregation"] = {
            "noncore_evidence_total": noncore_total,
            "corpus_related_fulltext": corpus_related_total,
            "corpus_related_fulltext_target": corpus_related_target,
            "release_gate_passed": release_gate_passed,
            "release_gate_reason": (
                "imported_related_full_text_target_met"
                if corpus_related_total >= corpus_related_target
                else "direct_supportive_core_available"
            ),
            "noncore_evidence_pool_counts": dict(bucket.get("noncore_evidence_pool_counts") or {}),
            "direct_core_evidence_allowed": False,
            "visual_evidence_count": int(bucket.get("visual_evidence_count") or 0),
            "visual_evidence_gate_policy": "candidate_only_until_human_review",
        }
        gap["visual_evidence_notes"] = list(bucket.get("visual_evidence_notes") or [])[:12]
        gap["visual_evidence_gate_policy"] = "candidate_only_until_human_review"
        gap["gap_epistemic_audit"] = {
            "passes": True,
            "category": "component_bridge_gap_synthesis",
            "verdict": "COMPONENT_BRIDGE_CONTEXT_WITHOUT_FINAL_DIRECT_CORE_VALIDATION",
            "direct_core_evidence_allowed": False,
            "forbidden_claim": "final_object_directly_validated",
        }
        gap["source_evidence_units"] = source_units
        gap["source_candidate_provenance"] = {
            "sub_hypothesis_id": str(sh_id),
            "paper_ids": [str(item.get("paper_id") or "") for item in pool_items[:8]],
            "source_unit_ids": [str(item.get("source_unit_id") or "") for item in source_units],
            "provenance_complete": bool(source_units),
            "source": "component_bridge_gap_synthesis",
        }
        gap["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
        _attach_restricted_component_bridge_role_contract(
            gap,
            _declared_subhypothesis_bridge_role_contract(
                project,
                sh_id,
                source_units=source_units,
            ),
        )
        if gap.get("restricted_bridge_role_contract_ready") is True:
            mark_restricted_component_bridge_hypothesis_policy(gap)
        else:
            gap["eligible_for_hypothesis_generation"] = False
        gaps.append(assess_gap_dict(project, gap))
    return gaps


def detect_noncore_evidence_integration_gaps(project: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    aggregation = (
        project.get("papergraph_evidence_aggregation")
        if isinstance(project.get("papergraph_evidence_aggregation"), dict)
        else {}
    )
    if not aggregation:
        aggregation = build_papergraph_evidence_aggregation(project)
        project["papergraph_evidence_aggregation"] = aggregation
    buckets = aggregation.get("subhypotheses") if isinstance(aggregation.get("subhypotheses"), dict) else {}
    focus_lookup = _subhypothesis_focus_lookup(project)
    records_by_id = {
        str(record.get("paper_id") or ""): record
        for record in project.get("papergraph", []) if isinstance(record, dict)
    }
    gaps: list[dict[str, Any]] = []
    for sh_id, bucket in buckets.items():
        if len(gaps) >= max(0, int(limit)):
            break
        if not isinstance(bucket, dict):
            continue
        noncore_total = int(bucket.get("noncore_evidence_total") or 0)
        core_total = sum(
            int(bucket.get(key) or 0)
            for key in ("supportive_core", "opposing_core", "boundary_core", "mixed_core")
        )
        if noncore_total <= 0:
            continue
        # If core evidence already creates a higher-priority conflict/boundary
        # gap, leave that to detect_conflict_boundary_gaps.  This detector is
        # for "not empty, but not yet core" situations.
        if core_total > 0 and not bucket.get("noncore_missing_contract_requirement_counts"):
            continue
        noncore_pool = bucket.get("noncore_evidence_pool") if isinstance(bucket.get("noncore_evidence_pool"), dict) else {}
        pool_name, pool_items = _dominant_noncore_pool(noncore_pool)
        if not pool_name or not pool_items:
            continue
        missing_axes = (
            bucket.get("noncore_missing_contract_requirement_counts")
            if isinstance(bucket.get("noncore_missing_contract_requirement_counts"), dict)
            else {}
        )
        focus_meta = focus_lookup.get(str(sh_id), {})
        description, research_path = _noncore_gap_description(
            sub_hypothesis_id=str(sh_id),
            focus=str(focus_meta.get("focus") or bucket.get("focus") or sh_id),
            scientific_object=str(focus_meta.get("scientific_object") or bucket.get("scientific_object") or ""),
            pool_name=pool_name,
            missing_axes={str(k): int(v or 0) for k, v in missing_axes.items()},
        )
        references = []
        source_units: list[dict[str, Any]] = []
        for item in pool_items[:8]:
            ref = str(item.get("citation") or item.get("title") or "")
            if ref and ref not in references:
                references.append(ref)
            paper_id = str(item.get("paper_id") or "")
            record = records_by_id.get(paper_id, {})
            excerpt = str(
                record.get("full_text_excerpt")
                or record.get("abstract")
                or record.get("conclusion")
                or record.get("title")
                or ""
            ).strip()
            if excerpt:
                excerpt_window = excerpt[:1200]
                source_units.append({
                    "paper_id": paper_id,
                    "source_unit_id": f"{paper_id}:noncore_evidence_pool:{pool_name}",
                    "source_field": "noncore_evidence_pool",
                    "excerpt": excerpt_window,
                    "excerpt_hash": sha256(excerpt_window.encode("utf-8")).hexdigest()[:16],
                    "binding_status": "noncore_related_evidence",
                    "evidence_role": str(item.get("evidence_role") or ""),
                    "missing_contract_requirements": list(
                        item.get("missing_contract_requirements") or []
                    ),
                })
        gap = make_gap(
            gap_type="noncore_evidence_integration_gap",
            description=description,
            supporting_references=references,
            suggested_research_path=research_path,
            value_argument=(
                "This is a high-value gap because the corpus is not empty: related method, platform, foundation, "
                "component, adverse, or boundary evidence exists, but it has not been converted into SH-specific "
                "causal validation with the declared endpoint and comparator."
            ),
            hypothesis_ingredients={
                "methods": [pool_name.replace("_", " ")],
                "scenarios": [str(focus_meta.get("focus") or bucket.get("focus") or sh_id)],
                "benchmarks": ["declared comparator or baseline"],
                "measurement_resources": ["noncore evidence pool"],
                "measurable_metrics": [
                    axis.replace("_", " ")
                    for axis in list(missing_axes.keys())[:4]
                ] or ["declared endpoint/readout"],
            },
            project_id=str(project.get("id") or project.get("project_id") or ""),
        )
        gap["sub_hypothesis_id"] = str(sh_id)
        gap["noncore_evidence_pool"] = {
            key: list(value)[:8]
            for key, value in noncore_pool.items()
            if isinstance(value, list) and value
        }
        gap["noncore_evidence_pool_counts"] = dict(bucket.get("noncore_evidence_pool_counts") or {})
        gap["noncore_missing_contract_requirement_counts"] = dict(missing_axes)
        gap["papergraph_evidence_aggregation"] = {
            "supportive_core": int(bucket.get("supportive_core") or 0),
            "opposing_core": int(bucket.get("opposing_core") or 0),
            "boundary_core": int(bucket.get("boundary_core") or 0),
            "mixed_core": int(bucket.get("mixed_core") or 0),
            "noncore_evidence_total": noncore_total,
            "noncore_evidence_pool_counts": dict(bucket.get("noncore_evidence_pool_counts") or {}),
            "visual_evidence_count": int(bucket.get("visual_evidence_count") or 0),
            "visual_evidence_gate_policy": "candidate_only_until_human_review",
        }
        gap["visual_evidence_notes"] = list(bucket.get("visual_evidence_notes") or [])[:12]
        gap["visual_evidence_gate_policy"] = "candidate_only_until_human_review"
        gap["gap_epistemic_audit"] = {
            "passes": True,
            "category": "noncore_related_evidence_integration_gap",
            "verdict": "NONCORE_EVIDENCE_INTEGRATION_GAP",
            "noncore_pool": pool_name,
            "missing_core_axis_counts": dict(missing_axes),
        }
        gap["source_evidence_units"] = source_units
        gap["source_candidate_provenance"] = {
            "paper_ids": [str(item.get("paper_id") or "") for item in pool_items[:8]],
            "source_unit_ids": [str(item.get("source_unit_id") or "") for item in source_units],
            "provenance_complete": bool(source_units),
            "source": "noncore_evidence_pool",
        }
        gap["gap_candidate_pool"] = MECHANISM_DISCOVERY_LEAD_POOL
        gap["eligible_for_hypothesis_generation"] = True
        gaps.append(assess_gap_dict(project, gap))
    return gaps


def explicit_gap_predicate_assessment(text: Any) -> dict[str, Any]:
    """Decide whether a source fragment asserts missing knowledge.

    This is intentionally separate from mechanism-axis classification.  A
    sentence may discuss temperature, an interface, a model, or a measurement
    without asserting that anything is unknown.
    """
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    for category, predicates in _EXPLICIT_GAP_PREDICATE_RULES:
        matches = [predicate for predicate in predicates if phrase_in_text(predicate, normalized)]
        if matches:
            return {
                "passes": True,
                "category": category,
                "matched_predicates": matches[:4],
                "verdict": "EXPLICIT_SCIENTIFIC_GAP_PREDICATE",
            }
    return {
        "passes": False,
        "category": "descriptive_or_rationale_only",
        "matched_predicates": [],
        "verdict": "NO_EXPLICIT_SCIENTIFIC_GAP_PREDICATE",
    }


def _provenance_terms(value: Any) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_+./-]{2,}|[\u4e00-\u9fff]{2,}", str(value or "").lower())
        if token not in _GAP_PROVENANCE_STOPWORDS
    }


def bind_record_source_unit(
    record: dict[str, Any],
    source_text: Any,
    source_location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a discovery seed to one paper-qualified bounded source unit."""
    try:
        from ._evidence_fragment_alignment import build_evidence_units
    except ImportError:
        from _evidence_fragment_alignment import build_evidence_units
    text = re.sub(r"\s+", " ", str(source_text or "")).strip()
    paper_id = str(record.get("paper_id") or record.get("doi") or "").strip()
    genre_payload = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
    alignment_payload = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    paper_genre = str(genre_payload.get("genre") or record.get("publication_type") or "")
    evidence_kind = str(record.get("evidence_kind") or alignment_payload.get("evidence_kind") or "")
    evidence_lane = str(record.get("evidence_lane") or alignment_payload.get("evidence_lane") or "")
    experiment_id = str(
        record.get("experiment_id") or record.get("study_id") or record.get("trial_id")
        or record.get("dataset_id") or record.get("cohort_id") or record.get("simulation_id")
        or (f"paper:{paper_id}" if paper_id else "")
    )
    source_type = (
        "fulltext"
        if any(str(record.get(key) or "").strip() for key in ("full_text_excerpt", "fulltext", "pdf_text", "extracted_text"))
        else "abstract"
    )
    units = build_evidence_units(record, window_size=3)
    query = text.lower()
    query_terms = _provenance_terms(text)
    best: dict[str, Any] = {}
    best_score = 0.0
    for unit in units:
        excerpt = re.sub(r"\s+", " ", str(unit.get("excerpt") or "")).strip().lower()
        if not excerpt:
            continue
        if query and (query in excerpt or excerpt in query):
            score = 2.0 + min(len(query), len(excerpt)) / max(1, max(len(query), len(excerpt)))
        else:
            unit_terms = _provenance_terms(excerpt)
            overlap = query_terms & unit_terms
            score = len(overlap) / max(1, len(query_terms | unit_terms))
        if score > best_score:
            best_score = score
            best = unit
    # An exact local unit is the normal path because the signal was extracted
    # from this record.  The fallback remains paper-qualified but explicitly
    # says that the local sentence window could not be re-resolved.
    if best and (best_score >= 2.0 or best_score >= 0.32):
        return {
            "paper_id": str(best.get("paper_id") or paper_id),
            "source_unit_id": str(best.get("source_unit_id") or ""),
            "excerpt_hash": str(best.get("excerpt_hash") or ""),
            "source_field": str(best.get("source_field") or ""),
            "section": str(best.get("source_field") or ""),
            "sentence_start": best.get("sentence_start"),
            "sentence_end": best.get("sentence_end"),
            "source_locator": str(best.get("source_locator") or ""),
            "excerpt": str(best.get("excerpt") or "")[:1200],
            "source_type": source_type,
            "source_location": dict(source_location or {}),
            "binding_status": "SOURCE_UNIT_VERIFIED",
            "paper_genre": paper_genre,
            "evidence_kind": evidence_kind,
            "evidence_lane": evidence_lane,
            "experiment_id": experiment_id or f"paper:{str(best.get('paper_id') or paper_id)}",
        }
    if not paper_id:
        paper_id = f"paper_anon_{sha256(record_reference(record).encode('utf-8')).hexdigest()[:16]}"
    locator_payload = json.dumps(source_location or {}, ensure_ascii=False, sort_keys=True, default=str)
    excerpt_hash = sha256(text.encode("utf-8")).hexdigest()
    locator = f"unresolved_source_location:{sha256(locator_payload.encode('utf-8')).hexdigest()[:12]}"
    return {
        "paper_id": paper_id,
        "source_unit_id": f"{paper_id}:{locator}:{excerpt_hash[:16]}",
        "excerpt_hash": excerpt_hash,
        "source_field": "unresolved",
        "source_type": source_type,
        "section": "unresolved",
        "sentence_start": None,
        "sentence_end": None,
        "source_locator": locator,
        "excerpt": text[:1200],
        "source_location": dict(source_location or {}),
        "binding_status": "PAPER_BOUND_SOURCE_UNIT_UNRESOLVED",
        "paper_genre": paper_genre,
        "evidence_kind": evidence_kind,
        "evidence_lane": evidence_lane,
        "experiment_id": experiment_id or f"paper:{paper_id}",
    }


def bind_gap_predicate_context(
    project: dict[str, Any],
    record: dict[str, Any],
    sub_hypothesis_id: str,
    predicate_text: Any,
    source_location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a gap sentence and its minimum sufficient same-paper context."""
    branch = normalized_subhypothesis_id(sub_hypothesis_id)
    if _project_uses_research_question_evidence_v3(project):
        # The v2 path stores a raw source span plus explicit assertions.  It
        # must not rebuild a causal alignment card merely to re-anchor a
        # legacy predicate fragment.
        predicate_unit = bind_record_source_unit(record, predicate_text, source_location)
        predicate_unit["source_location"] = dict(source_location or predicate_unit.get("source_location") or {})
        predicate_unit.setdefault("binding_status", "SOURCE_UNIT_VERIFIED")
        return {
            "version": "gap_predicate_context_binding_v2_rejected_legacy_alignment",
            "sub_hypothesis_id": branch,
            "gap_predicate_fragment": predicate_unit,
            "contextual_source_evidence_units": [dict(predicate_unit)],
            "status": "STALE_SCHEMA_LEGACY_CAUSAL_ALIGNMENT_NOT_USED",
        }
    contracts = (
        project.get("subhypothesis_alignment_contracts")
        if isinstance(project.get("subhypothesis_alignment_contracts"), dict)
        else {}
    )
    contract = contracts.get(branch) if isinstance(contracts.get(branch), dict) else {}
    if not contract and branch:
        subhypothesis = next(
            (
                item for item in (project.get("sub_hypotheses") or [])
                if isinstance(item, dict) and normalized_subhypothesis_id(item.get("id")) == branch
            ),
            {},
        )
        if subhypothesis:
            try:
                from ._research_alignment import build_project_alignment_card, build_subhypothesis_alignment_contract
            except ImportError:
                from _research_alignment import build_project_alignment_card, build_subhypothesis_alignment_contract
            contract = build_subhypothesis_alignment_contract(
                project,
                subhypothesis,
                build_project_alignment_card(project),
            )
    try:
        from ._evidence_fragment_alignment import reanchor_gap_predicate_context
    except ImportError:
        from _evidence_fragment_alignment import reanchor_gap_predicate_context
    anchored = (
        reanchor_gap_predicate_context(record, contract, predicate_text, adjacent_sentences=2)
        if contract else {}
    )
    predicate_unit = (
        dict(anchored.get("gap_predicate_fragment") or {})
        if isinstance(anchored.get("gap_predicate_fragment"), dict)
        else bind_record_source_unit(record, predicate_text, source_location)
    )
    predicate_unit["source_location"] = dict(source_location or predicate_unit.get("source_location") or {})
    predicate_unit.setdefault("binding_status", "SOURCE_UNIT_VERIFIED")
    contextual_units: list[dict[str, Any]] = []
    for unit in anchored.get("contextual_source_evidence_units", []) if isinstance(anchored, dict) else []:
        if not isinstance(unit, dict):
            continue
        contextual = dict(unit)
        contextual["source_location"] = dict(source_location or contextual.get("source_location") or {})
        contextual.setdefault("binding_status", "SOURCE_UNIT_VERIFIED")
        contextual_units.append(contextual)
    if not contextual_units:
        contextual_units = [dict(predicate_unit)]
    return {
        "version": "gap_predicate_context_binding_v1",
        "status": str(anchored.get("status") or "SOURCE_TEXT_UNRESOLVED"),
        "gap_predicate_fragment_ref": str(
            anchored.get("gap_predicate_fragment_ref")
            or predicate_unit.get("source_unit_id")
            or ""
        ),
        "gap_predicate_source_unit": predicate_unit,
        "object_context_fragment_refs": list(anchored.get("object_context_fragment_refs") or []),
        "causal_role_fragment_refs": list(anchored.get("causal_role_fragment_refs") or []),
        "minimum_sufficient_context_fragment_ref": str(
            anchored.get("minimum_sufficient_context_fragment_ref") or ""
        ),
        "contextual_source_evidence_units": contextual_units,
        "contextual_object_confirmed": bool(anchored.get("contextual_object_confirmed")),
        "predicate_match": dict(anchored.get("predicate_match") or {}),
    }


def default_gap_candidate_pool(gap_type: str) -> str:
    if gap_type in {"evidence_extraction_shortage", "causal_evidence_missing", "causal_chain_break"}:
        return EVIDENCE_EXTRACTION_SHORTAGE_POOL
    if gap_type in LANDSCAPE_DIAGNOSTIC_TYPES:
        return LANDSCAPE_DIAGNOSTIC_POOL
    if gap_type in SECONDARY_RESEARCH_OPPORTUNITY_TYPES or gap_type in {"implicit_tabi"}:
        return SECONDARY_RESEARCH_OPPORTUNITY_POOL
    if gap_type in EVIDENCE_DERIVED_GAP_GENERATOR_TYPES or gap_type in {"problem", "direct_gap_signal"}:
        return COMPOSITE_GAP_AUDIT_POOL
    return SECONDARY_RESEARCH_OPPORTUNITY_POOL

def claim_polarity(text: str) -> str:
    lowered = text.lower()
    positive_terms = (
        "support",
        "supports",
        "confirm",
        "consistent with",
        "improve",
        "outperform",
        "effective",
        "robust",
        "stable",
        "explains",
        "predicts",
        "evidence for",
    )
    negative_terms = (
        "contradict",
        "inconsistent",
        "fails",
        "failure",
        "not support",
        "no evidence",
        "cannot",
        "unstable",
        "discrepancy",
        "does not explain",
        "challenges",
        "undermines",
    )
    positive_count = sum(1 for term in positive_terms if phrase_in_text(term, lowered))
    negative_count = sum(1 for term in negative_terms if phrase_in_text(term, lowered))
    if positive_count > negative_count:
        return "positive"
    if negative_count > positive_count:
        return "negative"
    return "neutral"

def phrase_in_text(phrase: str, text: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    normalized = normalize_space(phrase).lower()
    if not normalized:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(normalized).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None

def first_polar_sentence(text: str, polarity: str) -> str:
    terms = (
        ("support", "confirm", "consistent", "improve", "outperform", "effective", "robust", "stable", "explains", "predicts")
        if polarity == "positive"
        else ("contradict", "inconsistent", "fails", "failure", "not support", "no evidence", "cannot", "unstable", "discrepancy", "challenges")
    )
    return first_sentence_with_terms(text, terms)

def first_sentence_with_terms(text: str, terms: tuple[str, ...]) -> str:
    try:
        from ._utils import split_sentences, trim_text
    except ImportError:
        from _utils import split_sentences, trim_text
    for sentence in split_sentences(text):
        lowered = sentence.lower()
        if any(term in lowered for term in terms):
            return trim_text(sentence, 260)
    return ""


def detect_causal_chain_break_gaps(project: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    """Retired V1 causal-chain detector.

    Causal identification remains a supported V3 gap type, but its
    candidates are emitted by the typed assertion detectors and must carry a
    current research-question contract. No missing chain edge is a gap by
    itself.
    """
    del project, limit
    return []


def causal_chain_explicit_gap_signal(
    record: dict[str, Any],
    chain: dict[str, Any],
    missing_kind: str,
) -> dict[str, Any]:
    """Return a same-paper source signal that explicitly states the missing link."""
    if not isinstance(record, dict) or not record:
        return {}
    chain_text = " ".join(
        [str(chain.get("trigger") or ""), str(chain.get("outcome") or ""), str(missing_kind or "")]
        + [
            str(step.get("claim") or step.get("text") or "") if isinstance(step, dict) else str(step)
            for step in (chain.get("steps") or [])
        ]
    )
    chain_terms = _provenance_terms(chain_text)
    for signal in record.get("gap_signals", []) if isinstance(record.get("gap_signals"), list) else []:
        if not isinstance(signal, dict):
            continue
        text = str(signal.get("text") or "").strip()
        predicate = explicit_gap_predicate_assessment(text)
        if not predicate.get("passes"):
            continue
        overlap = chain_terms & _provenance_terms(text)
        if len(overlap) < 2:
            continue
        location = signal.get("source_location") if isinstance(signal.get("source_location"), dict) else {}
        return {
            "signal_type": str(signal.get("signal_type") or ""),
            "text": text,
            "matched_chain_terms": sorted(overlap)[:10],
            "gap_predicate": predicate,
            "source_evidence": bind_record_source_unit(record, text, location),
        }
    return {}


def causal_edge_context_compatibility(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._scientific_gap_gate import causal_edge_temporal_order_audit
    except ImportError:
        from _scientific_gap_gate import causal_edge_temporal_order_audit
    left_context = left.get("context") if isinstance(left.get("context"), dict) else {}
    right_context = right.get("context") if isinstance(right.get("context"), dict) else {}
    matched: list[str] = []
    unknown: list[str] = []
    conflicts: list[str] = []
    left_branch = normalized_subhypothesis_id(left.get("sub_hypothesis_id"))
    right_branch = normalized_subhypothesis_id(right.get("sub_hypothesis_id"))
    if not left_branch or not right_branch:
        unknown.append("sub_hypothesis_id")
    elif left_branch == right_branch:
        matched.append("sub_hypothesis_id")
    else:
        conflicts.append("sub_hypothesis_id")
    for key in ("research_object", "species_or_system", "model_or_sample", "stage_or_regime", "timepoint"):
        left_value = str(left_context.get(key) or "").strip()
        right_value = str(right_context.get(key) or "").strip()
        if not left_value or not right_value:
            unknown.append(key)
            continue
        if text_jaccard(left_value, right_value) >= 0.45 or left_value.lower() in right_value.lower() or right_value.lower() in left_value.lower():
            matched.append(key)
        else:
            conflicts.append(key)
    object_matched = "research_object" in matched
    supporting_context_matched = any(key in matched for key in ("species_or_system", "model_or_sample", "stage_or_regime"))
    branch_matched = "sub_hypothesis_id" in matched
    compatible = bool(not conflicts and branch_matched and object_matched and supporting_context_matched)
    temporal_order = causal_edge_temporal_order_audit(left, right)
    return {
        "compatible": compatible,
        "status": (
            "CONTEXT_COMPATIBLE"
            if compatible
            else "CONTEXT_INCOMPATIBLE"
            if conflicts
            else "CONTEXT_UNDERDETERMINED"
        ),
        "matched_dimensions": matched,
        "unknown_dimensions": unknown,
        "conflicting_dimensions": conflicts,
        "left_context": left_context,
        "right_context": right_context,
        "temporal_order": temporal_order,
        "requirements": {
            "same_sub_hypothesis": branch_matched,
            "same_research_object": object_matched,
            "matched_system_sample_or_regime": supporting_context_matched,
            # A causal mediation claim needs affirmative ordering; merely not
            # finding a contradictory timepoint is not positive evidence.
            "time_order_not_conflicting": bool(temporal_order.get("passes")),
        },
    }


def normalized_subhypothesis_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(?<![A-Za-z0-9])SH\d+(?![A-Za-z0-9])", text, flags=re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return re.split(r"[:/|]", text, maxsplit=1)[0].strip()


def _papergraph_record_index_for_gap_binding(
    project: dict[str, Any] | None,
    records_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    if isinstance(records_by_id, dict):
        return records_by_id
    if not isinstance(project, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for record in list(project.get("papergraph") or []) + list(project.get("evidence") or []):
        if not isinstance(record, dict):
            continue
        for key in (
            record.get("paper_id"),
            record.get("doi"),
            record.get("openalex_id"),
            record.get("semantic_scholar_id"),
        ):
            identity = str(key or "").strip()
            if identity and identity not in output:
                output[identity] = record
    return output


def infer_gap_subhypothesis_id(
    gap: dict[str, Any],
    project: dict[str, Any] | None = None,
    records_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Recover the SH binding from a gap's provenance without inventing one.

    Many imported PaperGraph records intentionally store their branch binding
    in ``retrieval_branch``, ``alignment_assessment``, ``import_context`` or
    ``subhypothesis_bindings`` rather than duplicating a top-level
    ``sub_hypothesis_id``.  Gap routing and TABI diagnostics need the same
    normalization boundary; otherwise source-bound candidates look
    SH-unbound and are rejected as role conflicts.
    """

    if not isinstance(gap, dict):
        return ""
    direct = normalized_subhypothesis_id(gap.get("sub_hypothesis_id"))
    if direct:
        return direct
    candidates: list[str] = []

    def add(value: Any) -> None:
        normalized = normalized_subhypothesis_id(value)
        if normalized:
            candidates.append(normalized)

    for payload_key in (
        "pre_rank_source_role_audit",
        "original_source_role_audit",
        "source_candidate_provenance",
        "alignment_qualification",
    ):
        payload = gap.get(payload_key)
        if isinstance(payload, dict):
            add(payload.get("sub_hypothesis_id"))
            add(payload.get("source_sub_hypothesis_id"))

    index = _papergraph_record_index_for_gap_binding(project, records_by_id)
    source_units: list[dict[str, Any]] = []
    for unit in gap.get("source_evidence_units", []) if isinstance(gap.get("source_evidence_units"), list) else []:
        if isinstance(unit, dict):
            source_units.append(unit)
    provenance = gap.get("source_candidate_provenance")
    if isinstance(provenance, dict):
        for source in provenance.get("sources", []) if isinstance(provenance.get("sources"), list) else []:
            if isinstance(source, dict):
                source_units.append(source)
        if any(provenance.get(key) for key in ("paper_id", "source_unit_id", "sub_hypothesis_id")):
            source_units.append(provenance)

    for unit in source_units:
        add(unit.get("sub_hypothesis_id"))
        add(unit.get("source_sub_hypothesis_id"))
        identity = unit.get("source_identity") if isinstance(unit.get("source_identity"), dict) else {}
        add(identity.get("source_sub_hypothesis_id"))
        record = index.get(str(unit.get("paper_id") or "").strip())
        if isinstance(record, dict):
            for record_sh in _record_subhypothesis_ids_for_aggregation(record):
                add(record_sh)

    if not candidates:
        return ""
    counts = Counter(candidates)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def bind_gap_subhypothesis_id(
    gap: dict[str, Any],
    project: dict[str, Any] | None = None,
    records_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = dict(gap)
    branch = infer_gap_subhypothesis_id(item, project, records_by_id)
    if branch:
        item["sub_hypothesis_id"] = branch
        provenance = (
            dict(item.get("source_candidate_provenance") or {})
            if isinstance(item.get("source_candidate_provenance"), dict)
            else {}
        )
        if provenance:
            provenance["sub_hypothesis_id"] = branch
            sources = []
            for source in provenance.get("sources", []) if isinstance(provenance.get("sources"), list) else []:
                if isinstance(source, dict):
                    updated = dict(source)
                    updated.setdefault("sub_hypothesis_id", branch)
                    sources.append(updated)
            if sources:
                provenance["sources"] = sources
            item["source_candidate_provenance"] = provenance
        updated_units = []
        changed = False
        for unit in item.get("source_evidence_units", []) if isinstance(item.get("source_evidence_units"), list) else []:
            if isinstance(unit, dict):
                updated = dict(unit)
                if not normalized_subhypothesis_id(updated.get("sub_hypothesis_id")):
                    updated["sub_hypothesis_id"] = branch
                    changed = True
                updated_units.append(updated)
        if changed:
            item["source_evidence_units"] = updated_units
    return item


def causal_edge_summary(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = node_by_id.get(str(edge.get("source") or ""), {})
    target = node_by_id.get(str(edge.get("target") or ""), {})
    return {
        "source": str(source.get("label") or ""),
        "target": str(target.get("label") or ""),
        "relation": str(edge.get("relation") or "leads_to"),
        "citation": str(edge.get("citation") or ""),
        "evidence_excerpt": str(edge.get("evidence_excerpt") or ""),
        "evidence_type": str(edge.get("evidence_type") or "reported_unclassified"),
        "context": dict(edge.get("context") or {}) if isinstance(edge.get("context"), dict) else {},
        "interventions": [str(item) for item in edge.get("interventions", []) if str(item).strip()] if isinstance(edge.get("interventions"), list) else [],
        "paper_id": str(edge.get("paper_id") or ""),
        "sub_hypothesis_id": str(edge.get("sub_hypothesis_id") or ""),
        "source_unit_id": str(edge.get("source_unit_id") or ""),
        "excerpt_hash": str(edge.get("excerpt_hash") or ""),
        "source_location": dict(edge.get("source_location") or {}) if isinstance(edge.get("source_location"), dict) else {},
        "source_evidence": dict(edge.get("source_evidence") or {}) if isinstance(edge.get("source_evidence"), dict) else {},
    }


def causal_edge_strength(edge: dict[str, Any]) -> float:
    score = 0.25
    if str(edge.get("citation") or "").strip():
        score += 0.3
    if str(edge.get("evidence_excerpt") or "").strip():
        score += 0.2
    if isinstance(edge.get("interventions"), list) and edge.get("interventions"):
        score += 0.1
    evidence_type = str(edge.get("evidence_type") or "").lower()
    if evidence_type in {"experimental", "genetic", "pharmacological", "interventional", "observational"}:
        score += 0.15
    confidence = edge.get("confidence")
    if isinstance(confidence, (int, float)):
        score = 0.7 * score + 0.3 * max(0.0, min(1.0, float(confidence)))
    return round(max(0.0, min(1.0, score)), 3)


def causal_graph_alternative_paths(
    edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source_id: str,
    target_id: str,
    excluded_intermediate_id: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = []
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if isinstance(edge, dict):
            outgoing[str(edge.get("source") or "")].append(edge)
    for first in outgoing.get(source_id, []):
        intermediate_id = str(first.get("target") or "")
        if not intermediate_id or intermediate_id == excluded_intermediate_id:
            continue
        for second in outgoing.get(intermediate_id, []):
            if str(second.get("target") or "") != target_id:
                continue
            alternatives.append(
                {
                    "path": [
                        str(node_by_id.get(source_id, {}).get("label") or ""),
                        str(node_by_id.get(intermediate_id, {}).get("label") or ""),
                        str(node_by_id.get(target_id, {}).get("label") or ""),
                    ],
                    "supporting_references": sorted(
                        {str(first.get("citation") or ""), str(second.get("citation") or "")} - {""}
                    ),
                }
            )
            if len(alternatives) >= limit:
                return alternatives
    return alternatives


def detect_causal_mediation_gaps(
    project: dict[str, Any],
    limit: int = 4,
    rejected_audits: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Retired V1 mediation helper; use typed causal-identification gaps."""
    del project, limit
    if isinstance(rejected_audits, list):
        rejected_audits.append(
            {
                "status": "STALE_SCHEMA",
                "reason": "LEGACY_CAUSAL_MEDIATION_DETECTOR_RETIRED",
                "next_step": (
                    "Run the V3 typed assertion detectors for a declared "
                    "CAUSAL_IDENTIFICATION research question."
                ),
            }
        )
    return []


def causal_chain_entities(chain: dict[str, Any]) -> set[str]:
    values = [str(chain.get("trigger") or ""), str(chain.get("outcome") or "")]
    values.extend(str(item) for item in chain.get("observables", []) if str(item).strip())
    for step in chain.get("steps", []) if isinstance(chain.get("steps"), list) else []:
        values.append(str(step.get("claim") or step.get("text") or "") if isinstance(step, dict) else str(step))
    try:
        from ._gap_evidence_graph import assess_atomic_entity
    except ImportError:
        from _gap_evidence_graph import assess_atomic_entity
    return {
        entity.canonical_label
        for entity in (assess_atomic_entity(value) for value in values)
        if entity.valid
    }


def detect_cross_hypothesis_synthesis_gaps(project: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Retire cross-hypothesis causal synthesis outside V3 typed detection."""
    del project, limit
    return []


def cross_hypothesis_synthesis_report(project: dict[str, Any], limit: int = 3) -> dict[str, Any]:
    gaps = detect_cross_hypothesis_synthesis_gaps(project, limit=limit)
    return {
        "status": "evidence_linked" if gaps else "no_qualified_cross_hypothesis_link",
        "minimum_requirements": [
            "at least two sub-hypotheses",
            "exact shared causal entity, linked causal chain, or common readout",
            "a discriminating experimental, simulation, or derivation question",
        ],
        "gaps": gaps,
    }


def causal_chain_missing_requirement(chain: dict[str, Any]) -> tuple[str, str]:
    if not str(chain.get("trigger") or "").strip():
        return "trigger or boundary condition", "the condition that initiates the proposed mechanism"
    steps = chain.get("steps", []) if isinstance(chain.get("steps"), list) else []
    if not steps:
        if bool(chain.get("direct_relation")):
            return "", ""
        return "intermediate_mechanism", "an intermediate mechanism measured or derived between trigger and outcome"
    if any(isinstance(step, dict) and not str(step.get("evidence") or "").strip() for step in steps):
        return "step-level evidence", "a source excerpt, measurement, or derivation for each intermediate step"
    if not str(chain.get("outcome") or "").strip():
        return "outcome", "a measurable downstream outcome"
    if not list(chain.get("observables") or []):
        return "observability", "a concrete observable signal that can reveal the proposed link"
    if not list(chain.get("interventions") or []):
        return "intervention", "a feasible intervention or natural experiment that varies the causal input"
    return "", ""


def subhypothesis_for_causal_chain(
    project: dict[str, Any],
    chain: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = [candidate] if isinstance(candidate, dict) else project.get("sub_hypotheses", [])
    branch_id = str(chain.get("sub_hypothesis_id") or "")
    if branch_id:
        for item in candidates if isinstance(candidates, list) else []:
            if isinstance(item, dict) and str(item.get("id") or "") == branch_id:
                return item
    chain_text = " ".join(
        [
            str(chain.get("trigger") or ""),
            str(chain.get("outcome") or ""),
            " ".join(str(step.get("claim") or "") for step in chain.get("steps", []) if isinstance(step, dict)),
        ]
    ).lower()
    for item in candidates if isinstance(candidates, list) else []:
        if not isinstance(item, dict):
            continue
        focus = str(item.get("focus") or "").strip().lower()
        if focus and focus in chain_text:
            return item
    return {}


def detect_knowledge_gaps(project_id: str, max_gaps: int = 10) -> str:
    """Block the historical direct TanXi route in favor of the V3 GroupChat."""
    return json.dumps(
        {
            "status": "BLOCKED_V3_GROUPCHAT_ONLY",
            "project_id": project_id,
            "reason_code": "V3_GROUPCHAT_RESUME_REQUIRED",
            "instruction": (
                "Run or resume the project's AutoGen GroupChat. TanXi is executed there "
                "from a detached V3 evidence view and must not reconstruct a full project graph."
            ),
            "requested_max_gaps": max(0, int(max_gaps)),
        },
        ensure_ascii=False,
        indent=2,
    )


def run_tanxi_gap_exploration(
    project_id: str,
    target_domain: str = "",
    strategic_domains: list[str] | None = None,
    max_gaps: int = 10,
    semantic_audit_mode: Literal["deterministic", "llm_dual"] = "deterministic",
    groupchat_id: str = "",
    run_id: str = "",
) -> str:
    try:
        from ._project import science_state_manager
        from ._research_workflow import record_workflow_status, tanxi_workflow_contract, workflow_tool_gate
    except ImportError:
        from _project import science_state_manager
        from _research_workflow import record_workflow_status, tanxi_workflow_contract, workflow_tool_gate
    started_at = time.monotonic()
    manager = science_state_manager()
    log_event(
        "SCIENCE",
        "tanxi_started",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        semantic_audit_mode=semantic_audit_mode,
        max_gaps=max_gaps,
    )
    project = manager.load_tanxi_project_context(project_id)
    evidence_view = manager.load_tanxi_evidence_view(project_id)
    project["_tanxi_runtime_source_spans_by_id"] = {
        str(span.get("source_span_id") or span.get("source_unit_id") or ""): span
        for span in evidence_view.get("source_spans", [])
        if isinstance(span, dict)
        and str(span.get("source_span_id") or span.get("source_unit_id") or "")
    }
    log_event(
        "SCIENCE",
        "tanxi_evidence_view_loaded",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        paper_count=len(evidence_view.get("documents") or []),
        source_span_count=len(evidence_view.get("source_spans") or []),
        assertion_count=len(evidence_view.get("assertions") or []),
        input_fingerprint=str(evidence_view.get("input_fingerprint") or ""),
    )
    input_manifest_result = manager.persist_tanxi_input_manifest(
        project_id,
        evidence_view=evidence_view,
    )
    input_manifest_ref = dict(input_manifest_result.get("artifact_ref") or {})
    log_event(
        "SCIENCE",
        "tanxi_input_manifest_ready",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        status=str(input_manifest_result.get("status") or ""),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        paper_count=len(evidence_view.get("documents") or []),
        source_span_count=len(evidence_view.get("source_spans") or []),
        assertion_count=len(evidence_view.get("assertions") or []),
        input_fingerprint=str(evidence_view.get("input_fingerprint") or ""),
        tanxi_input_manifest_ref={
            key: value for key, value in input_manifest_ref.items() if key != "path"
        },
    )
    # Reject old or mixed SH collections before the workflow gate.  The V3
    # TanXi route has no causal-graph compatibility adapter, and the stale
    # marking is persisted so a caller sees a re-decomposition request rather
    # than a misleading empty candidate list.
    cutover = research_question_cutover_audit_v3(project)
    if not cutover.get("all_subhypotheses_v3"):
        manager.commit_v3_project_patch(
            project_id,
            field_updates={"research_question_cutover_audit": cutover},
            artifact_groups=("project",),
            expected_version=int(project.get("state_version") or 0),
            operation="RECORD_TANXI_V3_CUTOVER_BLOCK",
        )
        return json.dumps(
            {
                "schema_version": "tanxi_gap_report_v3",
                "project_id": project_id,
                "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                "ranked_gaps": [],
                "research_packages": [],
                "cutover_audit": cutover,
                "next_step": (
                    "Re-decompose every sub-hypothesis as an explicit ResearchQuestionContractV3; "
                    "legacy causal artifacts are stale and are not input to TanXi V3."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    gate = workflow_tool_gate(
        project,
        "run_tanxi_gap_exploration",
        {
            "target_domain": target_domain,
            "strategic_domains": list(strategic_domains or []),
            "max_gaps": max_gaps,
            "semantic_audit_mode": semantic_audit_mode,
        },
    )
    if not gate.get("allowed"):
        return json.dumps(dict(gate.get("result") or {}), ensure_ascii=False, indent=2)
    empty_corpus_diagnostic = (
        evidence_view.get("empty_corpus_diagnostic")
        if isinstance(evidence_view.get("empty_corpus_diagnostic"), dict)
        else {}
    )
    if str(evidence_view.get("corpus_status") or "") == "EMPTY_V3_CORPUS":
        status = str(
            empty_corpus_diagnostic.get("status")
            or "RETRIEVAL_COMPLETED_WITHOUT_ADMITTED_EVIDENCE"
        )
        report = {
            "schema_version": "tanxi_gap_report_v3",
            "project_id": project_id,
            "status": status,
            "ranked_gaps": [],
            "research_packages": [],
            "corpus_status": "EMPTY_V3_CORPUS",
            "retrieval_diagnostic": empty_corpus_diagnostic,
            "input_fingerprint": str(evidence_view.get("input_fingerprint") or ""),
            "next_step": (
                "Resume the V3 retrieval execution for the failed task stages, then rerun "
                "the AutoGen GroupChat after source spans and explicit assertions are admitted."
                if status == "RETRIEVAL_EXECUTION_FAILED_NO_CORPUS"
                else "Run the V3 slot retrieval and source-span extraction workflow before TanXi gap detection."
            ),
        }
        log_event(
            "SCIENCE",
            "tanxi_empty_v3_corpus",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            status=status,
            retrieval_execution_error_count=int(
                empty_corpus_diagnostic.get("retrieval_execution_error_count") or 0
            ),
            input_fingerprint=str(evidence_view.get("input_fingerprint") or ""),
        )
        return json.dumps(report, ensure_ascii=False, indent=2)
    # Historical causal graphs and matrix-derived gap pools are intentionally
    # not read by the V2 path.
    if semantic_audit_mode == "llm_dual":
        try:
            from ._gap_semantic_audit import llm_gap_semantic_auditor
        except ImportError:
            from _gap_semantic_audit import llm_gap_semantic_auditor
        semantic_auditor = lambda request: llm_gap_semantic_auditor(request, role="positive")
        red_team_auditor = lambda request: llm_gap_semantic_auditor(request, role="red_team")
    elif semantic_audit_mode == "deterministic":
        semantic_auditor = None
        red_team_auditor = None
    else:
        raise ValueError("semantic_audit_mode must be 'deterministic' or 'llm_dual'")
    log_event(
        "SCIENCE",
        "tanxi_graph_build_started",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        paper_count=len(evidence_view.get("documents") or []),
        source_span_count=len(evidence_view.get("source_spans") or []),
        assertion_count=len(evidence_view.get("assertions") or []),
        input_fingerprint=str(evidence_view.get("input_fingerprint") or ""),
    )
    last_graph_heartbeat_at = [time.monotonic()]

    def log_graph_progress(progress: dict[str, Any]) -> None:
        now = time.monotonic()
        processed_bucket_count = int(progress.get("processed_bucket_count") or 0)
        if (
            processed_bucket_count
            and processed_bucket_count < int(progress.get("bucket_count") or 0)
            and now - last_graph_heartbeat_at[0] < 15.0
        ):
            return
        last_graph_heartbeat_at[0] = now
        log_event(
            "SCIENCE",
            "tanxi_graph_build_progress",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            phase="GRAPH_BUILDING",
            elapsed_ms=round((now - started_at) * 1000, 2),
            assertion_count=len(evidence_view.get("assertions") or []),
            source_span_count=len(evidence_view.get("source_spans") or []),
            pair_bucket_count=int(progress.get("bucket_count") or 0),
            processed_bucket_count=processed_bucket_count,
            candidate_pair_count=int(progress.get("candidate_pair_count") or 0),
            selected_pair_count=int(progress.get("selected_pair_count") or 0),
            truncated_bucket_count=int(progress.get("truncated_bucket_count") or 0),
            input_fingerprint=str(evidence_view.get("input_fingerprint") or ""),
        )

    graph_result = manager.persist_tanxi_evidence_graph(
        project_id,
        evidence_view=evidence_view,
        progress_callback=log_graph_progress,
    )
    snapshot = graph_result["snapshot"]
    project["_tanxi_graph_snapshot"] = snapshot
    project["active_research_evidence_graph_ref"] = dict(
        graph_result.get("graph_snapshot_ref") or {}
    )
    project["state_version"] = int(graph_result.get("state_version") or project.get("state_version") or 0)
    log_event(
        "SCIENCE",
        "tanxi_graph_cache_hit" if graph_result.get("status") == "CACHE_HIT" else "tanxi_graph_persisted",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        source_span_count=int((snapshot.get("summary") or {}).get("source_span_count") or 0),
        assertion_count=int((snapshot.get("summary") or {}).get("explicit_assertion_count") or 0),
        pair_planner=dict(snapshot.get("comparability_pair_index_summary") or {}),
        input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
    )
    persisted_checkpoint = project.get("tanxi_run_checkpoint_v3")
    persisted_checkpoint = (
        persisted_checkpoint if isinstance(persisted_checkpoint, dict) else {}
    )
    tanxi_run_configuration = {
        "schema_version": "tanxi_run_configuration_v3",
        "semantic_audit_mode": str(semantic_audit_mode),
        "max_gaps": max(0, int(max_gaps)),
        "audit_frontier_policy_version": "fair_gap_audit_frontier_v3",
        "audit_candidate_budget_per_type_contract": 6,
    }
    tanxi_run_fingerprint = "sha256:" + sha256(
        json.dumps(
            {
                "evidence_input_fingerprint": str(snapshot.get("input_fingerprint") or ""),
                "configuration": tanxi_run_configuration,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    detector_checkpoint = (
        persisted_checkpoint
        if str(persisted_checkpoint.get("input_fingerprint") or "")
        == str(snapshot.get("input_fingerprint") or "")
        and str(persisted_checkpoint.get("tanxi_run_fingerprint") or "")
        == tanxi_run_fingerprint
        else {}
    )
    if (
        str(persisted_checkpoint.get("phase") or "") == "TANXI_REPORT_PERSISTED"
        and not bool(persisted_checkpoint.get("audit_continuation_pending"))
    ):
        persisted_report = manager._project_field_value(
            project_id,
            manager.get_project_manifest(project_id),
            "tanxi_gap_analysis",
            required=False,
        )
        if isinstance(persisted_report, dict):
            report_ref = persisted_report.get("research_evidence_graph_ref")
            if (
                isinstance(report_ref, dict)
                and str(report_ref.get("input_fingerprint") or "")
                == str(snapshot.get("input_fingerprint") or "")
                and str(persisted_report.get("tanxi_run_fingerprint") or "")
                == tanxi_run_fingerprint
            ):
                cached_report = copy.deepcopy(persisted_report)
                cached_report["status"] = "REUSED_PERSISTED_TANXI_REPORT"
                cached_report["tanxi_resume"] = {
                    "status": "TANXI_REPORT_REUSED",
                    "input_fingerprint": str(snapshot.get("input_fingerprint") or ""),
                    "tanxi_run_fingerprint": tanxi_run_fingerprint,
                    "groupchat_id": str(groupchat_id or ""),
                    "run_id": str(run_id or ""),
                }
                log_event(
                    "SCIENCE",
                    "tanxi_report_reused",
                    project_id=project_id,
                    groupchat_id=str(groupchat_id or ""),
                    run_id=str(run_id or ""),
                    elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
                    input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
                    tanxi_run_fingerprint=tanxi_run_fingerprint,
                )
                return json.dumps(cached_report, ensure_ascii=False, indent=2)

    checkpoint_state = copy.deepcopy(detector_checkpoint)

    def persist_checkpoint(
        *,
        phase: str,
        next_action: str,
    ) -> dict[str, Any]:
        checkpoint = {
            "schema_version": "tanxi_run_checkpoint_v3",
            "project_id": project_id,
            "groupchat_id": str(groupchat_id or ""),
            "run_id": str(run_id or ""),
            "input_fingerprint": str(snapshot.get("input_fingerprint") or ""),
            "tanxi_run_configuration": dict(tanxi_run_configuration),
            "tanxi_run_fingerprint": tanxi_run_fingerprint,
            "phase": phase,
            "tanxi_input_manifest_ref": dict(input_manifest_ref),
            "graph_snapshot_ref": dict(graph_result.get("graph_snapshot_ref") or {}),
            "completed_detector_ids": list(
                checkpoint_state.get("completed_detector_ids") or []
            ),
            "detector_result_refs": {
                str(detector_id): copy.deepcopy(detector_result_ref)
                for detector_id, detector_result_ref in (
                    checkpoint_state.get("detector_result_refs") or {}
                ).items()
                if isinstance(detector_result_ref, dict)
            },
            "detector_result_count": len(
                checkpoint_state.get("detector_result_refs") or {}
            ),
            "semantic_audit_results": dict(
                checkpoint_state.get("semantic_audit_results") or {}
            ),
            "semantic_audit_completed_candidate_ids": list(
                checkpoint_state.get("semantic_audit_completed_candidate_ids") or []
            ),
            "audit_frontier_resume_state_v3": dict(
                checkpoint_state.get("audit_frontier_resume_state_v3") or {}
            ),
            "audit_continuation_pending": bool(
                checkpoint_state.get("audit_continuation_pending")
            ),
            "next_action": next_action,
            "updated_at": time.time(),
        }
        manager.commit_v3_project_patch(
            project_id,
            field_updates={"tanxi_run_checkpoint_v3": checkpoint},
            artifact_groups=("workflow",),
            operation=f"CHECKPOINT_TANXI_V3_{phase}",
        )
        return checkpoint

    persist_checkpoint(
        phase="GRAPH_PERSISTED",
        next_action="run_tanxi_detectors",
    )

    def persist_detector_checkpoint(
        detector_id: str,
        progress: dict[str, Any],
    ) -> None:
        detector_result = progress.get("detector_result")
        if not isinstance(detector_result, dict):
            raise ValueError("TanXi detector checkpoint requires one detector result")
        stored = manager.persist_tanxi_detector_result(
            project_id,
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            detector_id=detector_id,
            detector_result=detector_result,
        )
        detector_result_refs = dict(
            checkpoint_state.get("detector_result_refs") or {}
        )
        detector_result_refs[detector_id] = dict(
            stored.get("artifact_ref") or {}
        )
        checkpoint_state["detector_result_refs"] = detector_result_refs
        checkpoint_state["completed_detector_ids"] = list(
            progress.get("completed_detector_ids") or []
        )
        checkpoint = persist_checkpoint(
            phase="DETECTORS_RUNNING",
            next_action="resume_remaining_tanxi_detectors",
        )
        log_event(
            "SCIENCE",
            "tanxi_detector_completed",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            detector_id=detector_id,
            completed_detector_count=len(checkpoint["completed_detector_ids"]),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
            input_fingerprint=checkpoint["input_fingerprint"],
            tanxi_run_fingerprint=tanxi_run_fingerprint,
        )

    def load_detector_checkpoint_result(
        detector_id: str,
        detector_result_ref: dict[str, Any],
    ) -> dict[str, Any]:
        return manager.get_tanxi_detector_result(
            project_id,
            detector_result_ref,
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            detector_id=detector_id,
        )

    def log_semantic_candidate_started(
        candidate_identity: str,
        progress: dict[str, Any],
    ) -> None:
        log_event(
            "SCIENCE",
            "tanxi_semantic_candidate_started",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            candidate_identity=candidate_identity,
            candidate_index=int(progress.get("candidate_index") or 0),
            candidate_count=int(progress.get("candidate_count") or 0),
            reused=bool(progress.get("reused") is True),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            tanxi_run_fingerprint=tanxi_run_fingerprint,
        )

    def persist_semantic_candidate_checkpoint(
        candidate_identity: str,
        progress: dict[str, Any],
    ) -> None:
        candidate_fingerprint = str(progress.get("candidate_fingerprint") or "")
        audited_candidate = progress.get("audited_candidate")
        if not candidate_identity or not candidate_fingerprint or not isinstance(audited_candidate, dict):
            raise ValueError(
                "TanXi semantic checkpoint requires one fingerprinted audited candidate"
            )
        audit_results = dict(checkpoint_state.get("semantic_audit_results") or {})
        audit_results[candidate_identity] = {
            "schema_version": "tanxi_semantic_audit_candidate_checkpoint_v1",
            "candidate_fingerprint": candidate_fingerprint,
            "semantic_audit_projection": _tanxi_semantic_audit_checkpoint_projection(
                audited_candidate
            ),
        }
        checkpoint_state["semantic_audit_results"] = audit_results
        checkpoint_state["semantic_audit_completed_candidate_ids"] = list(
            dict.fromkeys(
                list(
                    checkpoint_state.get("semantic_audit_completed_candidate_ids")
                    or []
                )
                + [candidate_identity]
            )
        )
        checkpoint = persist_checkpoint(
            phase="SEMANTIC_AUDIT_RUNNING",
            next_action="resume_remaining_tanxi_semantic_candidate_audits",
        )
        log_event(
            "SCIENCE",
            "tanxi_semantic_candidate_completed",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            candidate_identity=candidate_identity,
            candidate_index=int(progress.get("candidate_index") or 0),
            candidate_count=int(progress.get("candidate_count") or 0),
            completed_candidate_count=len(
                checkpoint["semantic_audit_completed_candidate_ids"]
            ),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            tanxi_run_fingerprint=tanxi_run_fingerprint,
        )

    def log_detector_started(progress: dict[str, Any]) -> None:
        log_event(
            "SCIENCE",
            "tanxi_detector_started",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            completed_detector_count=int(
                progress.get("completed_detector_count") or 0
            ),
            checkpointed_detector_count=int(
                progress.get("checkpointed_detector_count") or 0
            ),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            tanxi_run_fingerprint=tanxi_run_fingerprint,
        )

    def log_semantic_audit_started(progress: dict[str, Any]) -> None:
        log_event(
            "SCIENCE",
            "tanxi_semantic_audit_started",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            semantic_audit_mode=semantic_audit_mode,
            candidate_count=int(progress.get("candidate_count") or 0),
            checkpointed_candidate_count=int(
                progress.get("checkpointed_candidate_count") or 0
            ),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
            input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
            tanxi_run_fingerprint=tanxi_run_fingerprint,
        )

    try:
        report = tanxi_gap_exploration_report(
            project,
            max_gaps=max_gaps,
            semantic_auditor=semantic_auditor,
            red_team_auditor=red_team_auditor,
            graph_snapshot=snapshot,
            detector_checkpoint=detector_checkpoint,
            on_detector_complete=persist_detector_checkpoint,
            load_detector_result=load_detector_checkpoint_result,
            on_detector_started=log_detector_started,
            semantic_audit_checkpoint=detector_checkpoint,
            on_semantic_audit_started=log_semantic_audit_started,
            on_semantic_candidate_started=log_semantic_candidate_started,
            on_semantic_candidate_complete=persist_semantic_candidate_checkpoint,
        )
    finally:
        # Quotes stay only in the current bounded evidence-view cache.  Every
        # persistence exit below uses a reference-only projection.
        project.pop("_tanxi_runtime_source_spans_by_id", None)
    checkpoint_state["audit_frontier_resume_state_v3"] = dict(
        report.get("audit_frontier_resume_state_v3") or {}
    )
    checkpoint_state["audit_continuation_pending"] = bool(
        report.get("audit_continuation_pending")
    )
    persist_checkpoint(
        phase="DETECTORS_PERSISTED",
        next_action=(
            "resume_v3_tanxi_audit_frontier"
            if checkpoint_state["audit_continuation_pending"]
            else "run_tanxi_semantic_audit"
        ),
    )
    log_event(
        "SCIENCE",
        "tanxi_semantic_audit_completed",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        semantic_audit_mode=semantic_audit_mode,
        candidate_count=len(report.get("candidate_ledger") or report.get("gap_candidate_ledger") or {}),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
        tanxi_run_fingerprint=tanxi_run_fingerprint,
    )
    report["tanxi_run_configuration"] = tanxi_run_configuration
    report["tanxi_run_fingerprint"] = tanxi_run_fingerprint
    for candidate in report.get("ranked_gaps", []) if isinstance(report.get("ranked_gaps"), list) else []:
        if not isinstance(candidate, dict):
            continue
        assessment = assessment_of(candidate)
        log_event(
            "SCIENCE",
            "tanxi_gap_candidate_emitted",
            project_id=project_id,
            groupchat_id=str(groupchat_id or ""),
            run_id=str(run_id or ""),
            candidate_identity=str(candidate.get("candidate_identity") or ""),
            gap_id=str(candidate.get("gap_id") or ""),
            gap_type=str(assessment.get("gap_type") or ""),
            candidate_stage=str(assessment.get("candidate_stage") or ""),
            route=str(assessment.get("route") or ""),
            semantic_verdict=str(assessment.get("semantic_verdict") or ""),
            decision_reasons=list(assessment.get("decision_reasons") or []),
        )
        if assessment.get("route") == GapRoute.TARGETED_RETRIEVAL.value:
            log_event(
                "SCIENCE",
                "tanxi_gap_targeted_retrieval_scheduled",
                project_id=project_id,
                groupchat_id=str(groupchat_id or ""),
                run_id=str(run_id or ""),
                candidate_identity=str(candidate.get("candidate_identity") or ""),
                gap_type=str(assessment.get("gap_type") or ""),
                retrieval_plan_schema=str((candidate.get("retrieval_plan") or {}).get("schema_version") or ""),
                missing_axes=list((candidate.get("retrieval_plan") or {}).get("missing_axes") or []),
                gap_resolution_work_item_id=str(
                    (candidate.get("retrieval_work_item_v3") or {}).get("work_item_id") or ""
                ),
                target_slot_ids=list(
                    (candidate.get("gap_resolution_retrieval") or {}).get("target_slot_ids") or []
                ),
                retrieval_status=str(
                    (candidate.get("gap_resolution_retrieval") or {}).get("status") or ""
                ),
            )
    for diagnostic in report.get("diagnostics", []) if isinstance(report.get("diagnostics"), list) else []:
        if isinstance(diagnostic, dict):
            log_event(
                "SCIENCE",
                "tanxi_gap_candidate_rejected_or_unmatched",
                project_id=project_id,
                groupchat_id=str(groupchat_id or ""),
                run_id=str(run_id or ""),
                reason=str(diagnostic.get("reason") or diagnostic.get("stage") or "UNSPECIFIED"),
                detector_id=str(diagnostic.get("detector_id") or ""),
            )
    for recovery_plan in report.get("slot_directed_recovery_plans", []) if isinstance(report.get("slot_directed_recovery_plans"), list) else []:
        if isinstance(recovery_plan, dict):
            log_event(
                "SCIENCE",
                "tanxi_slot_directed_recovery_scheduled",
                project_id=project_id,
                groupchat_id=str(groupchat_id or ""),
                run_id=str(run_id or ""),
                sub_hypothesis_id=str(recovery_plan.get("sub_hypothesis_id") or ""),
                target_slot_ids=list(recovery_plan.get("target_slot_ids") or []),
            )
    report["method_scenario_benchmark_louvain"] = {
        "status": "NOT_USED_BY_RESEARCH_QUESTION_EVIDENCE_V3",
        "reason": "Gap discovery uses source spans and evidence contracts rather than matrix topology.",
    }
    ranked = report.get("ranked_gaps", []) if isinstance(report.get("ranked_gaps"), list) else []
    msb_louvain = report["method_scenario_benchmark_louvain"]
    workflow_contract = tanxi_workflow_contract(report)
    workflow_state = record_workflow_status(
        project,
        stage="tanxi",
        **workflow_contract,
    )
    report.update(workflow_state)
    # TanXi creates source-signal and causal gaps in addition to the older
    # coverage scan.  Persist the ranked objects themselves, not only their
    # mechanism drafts.  Otherwise Socrates can resolve an id from the
    # transient report while MingLi later reloads a canonical list that never
    # contained that id.
    compact_report = compact_tanxi_gap_report(report)
    persisted_ranked = list(compact_report.get("ranked_gaps") or [])
    project["knowledge_gaps"] = synchronize_tanxi_ranked_gaps(
        project.get("knowledge_gaps", []),
        persisted_ranked,
        limit=max_gaps,
    )
    project["tanxi_gap_analysis"] = compact_report
    project["primary_research_candidates"] = list(
        compact_report.get("primary_research_candidates") or []
    )
    project["primary_mechanism_candidates"] = list(
        compact_report.get("primary_mechanism_candidates") or []
    )
    project["research_packages"] = _tanxi_reference_only_value(
        list(report.get("research_packages") or [])
    )
    project["targeted_retrieval_candidate_ids"] = [
        str(item.get("gap_id") or "")
        for item in report.get("targeted_retrieval_candidates", [])
        if isinstance(item, dict) and str(item.get("gap_id") or "")
    ]
    project["gap_resolution_work_items_v3"] = list(
        compact_report.get("gap_resolution_work_items_v3", [])
    )
    project["slot_directed_recovery_plans"] = list(
        report.get("slot_directed_recovery_plans", [])
    )
    project["gap_candidate_ledger"] = dict(report.get("gap_candidate_ledger") or {})
    project["tanxi_candidate_funnel"] = dict(report.get("tanxi_candidate_funnel") or {})
    project["verification_tasks"] = list(report.get("verification_tasks", []))
    project["near_pass_targeted_retrieval_tasks"] = list(
        report.get("near_pass_targeted_retrieval_tasks", [])
    )
    project["subhypothesis_gap_handoffs"] = list(report.get("subhypothesis_gap_handoffs", []))
    project["rejected_scientific_candidates"] = list(report.get("rejected_scientific_candidates", []))
    project["evidence_extraction_shortage_ids"] = [
        str(item.get("gap_id") or "")
        for item in report.get("evidence_extraction_shortages", [])
        if isinstance(item, dict) and str(item.get("gap_id") or "")
    ]
    project["rejected_evidence_audit_ids"] = [
        str(item.get("gap_id") or "")
        for item in report.get("rejected_evidence_audit", [])
        if isinstance(item, dict) and str(item.get("gap_id") or "")
    ]
    project.pop("_tanxi_graph_snapshot", None)
    field_updates = {
        "knowledge_gaps": project["knowledge_gaps"],
        "tanxi_gap_analysis": project["tanxi_gap_analysis"],
        "primary_research_candidates": project["primary_research_candidates"],
        "primary_mechanism_candidates": project["primary_mechanism_candidates"],
        "research_packages": project["research_packages"],
        "targeted_retrieval_candidate_ids": project["targeted_retrieval_candidate_ids"],
        "gap_resolution_work_items_v3": project["gap_resolution_work_items_v3"],
        "slot_directed_recovery_plans": project["slot_directed_recovery_plans"],
        "gap_candidate_ledger": project["gap_candidate_ledger"],
        "tanxi_candidate_funnel": project["tanxi_candidate_funnel"],
        "verification_tasks": project["verification_tasks"],
        "near_pass_targeted_retrieval_tasks": project["near_pass_targeted_retrieval_tasks"],
        "subhypothesis_gap_handoffs": project["subhypothesis_gap_handoffs"],
        "rejected_scientific_candidates": project["rejected_scientific_candidates"],
        "evidence_extraction_shortage_ids": project["evidence_extraction_shortage_ids"],
        "rejected_evidence_audit_ids": project["rejected_evidence_audit_ids"],
        "research_workflow_control": project.get("research_workflow_control") or {},
        "tanxi_run_checkpoint_v3": {
            "schema_version": "tanxi_run_checkpoint_v3",
            "project_id": project_id,
            "groupchat_id": str(groupchat_id or ""),
            "run_id": str(run_id or ""),
            "input_fingerprint": str(snapshot.get("input_fingerprint") or ""),
            "tanxi_run_configuration": dict(tanxi_run_configuration),
            "tanxi_run_fingerprint": tanxi_run_fingerprint,
            "phase": "TANXI_REPORT_PERSISTED",
            "tanxi_input_manifest_ref": dict(input_manifest_ref),
            "graph_snapshot_ref": dict(graph_result.get("graph_snapshot_ref") or {}),
            "completed_detector_ids": list(
                checkpoint_state.get("completed_detector_ids") or []
            ),
            "semantic_audit_completed_candidate_ids": list(
                checkpoint_state.get("semantic_audit_completed_candidate_ids") or []
            ),
            "audit_frontier_resume_state_v3": dict(
                checkpoint_state.get("audit_frontier_resume_state_v3") or {}
            ),
            "audit_continuation_pending": bool(
                checkpoint_state.get("audit_continuation_pending")
            ),
            "next_action": (
                "resume_v3_tanxi_audit_frontier"
                if checkpoint_state.get("audit_continuation_pending")
                else "continue_v3_groupchat_after_tanxi"
            ),
            "updated_at": time.time(),
        },
    }
    manager.commit_v3_project_patch(
        project_id,
        field_updates=field_updates,
        artifact_groups=("gaps", "workflow"),
        operation="PERSIST_TANXI_V3_REPORT",
    )
    log_event(
        "SCIENCE",
        "tanxi_report_persisted",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        ranked=len(report.get("ranked_gaps", [])),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
        input_fingerprint=str(snapshot.get("input_fingerprint") or ""),
    )
    log_event(
        "SCIENCE",
        "tanxi_gap_exploration",
        project_id=project_id,
        groupchat_id=str(groupchat_id or ""),
        run_id=str(run_id or ""),
        ranked=len(report.get("ranked_gaps", [])),
        evidence_graph_schema=(report.get("evidence_graph") or {}).get("schema_version"),
        explicit_assertions=int(((report.get("evidence_graph") or {}).get("summary") or {}).get("explicit_assertion_count") or 0),
    )
    return json.dumps(compact_report, ensure_ascii=False, indent=2)


def apply_gap_retrieval_assessment(
    project_id: str,
    gap_id: str,
    retrieval_assessment: dict[str, Any],
) -> str:
    """Block direct gap-retrieval assessment outside the V3 GroupChat."""
    return json.dumps(
        {
            "status": "BLOCKED_V3_GROUPCHAT_ONLY",
            "project_id": project_id,
            "gap_id": gap_id,
            "reason_code": "V3_GROUPCHAT_RESUME_REQUIRED",
            "instruction": (
                "Resume the owning AutoGen GroupChat. Direct gap-retrieval assessment "
                "cannot rebuild or mutate a detached V3 evidence graph."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def execute_research_question_retrieval_plan(
    project_id: str,
    sub_hypothesis_id: str,
    retrieval_results: list[dict[str, Any]] | None,
) -> str:
    """Persist one authorised V3 slot-retrieval execution.

    Provider adapters remain responsible for discovering and importing source
    documents.  This public workflow boundary records which exact V3 tasks
    were executed and which imported source ids were inspected.  It never
    turns an empty result into a scientific gap or a source assertion.
    """
    try:
        from ._project import science_state_manager
        from ._research_workflow import (
            RESEARCH_QUESTION_RETRIEVAL_STAGE,
            TANXI_TOOL,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
        from ._subhypothesis_retrieval import record_research_question_query_results
    except ImportError:
        from _project import science_state_manager
        from _research_workflow import (
            RESEARCH_QUESTION_RETRIEVAL_STAGE,
            TANXI_TOOL,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
        from _subhypothesis_retrieval import record_research_question_query_results
    manager = science_state_manager()
    project = manager.load_tanxi_project_context(project_id)
    normalized_sub_id = str(sub_hypothesis_id or "").strip()
    tool_input = {"sub_hypothesis_id": normalized_sub_id}
    gate = workflow_tool_gate(project, RESEARCH_QUESTION_RETRIEVAL_STAGE, tool_input)
    if not gate.get("allowed"):
        return json.dumps(dict(gate.get("result") or {}), ensure_ascii=False, indent=2)
    sub_hypothesis = next(
        (
            item for item in project.get("sub_hypotheses", [])
            if isinstance(item, dict)
            and str(item.get("id") or item.get("sub_hypothesis_id") or "") == normalized_sub_id
        ),
        None,
    )
    if not isinstance(sub_hypothesis, dict):
        raise ValueError(f"Unknown V3 sub_hypothesis_id: {normalized_sub_id!r}")
    if retrieval_results is not None and (
        not isinstance(retrieval_results, list)
        or any(not isinstance(item, dict) for item in retrieval_results)
    ):
        raise ValueError("retrieval_results must be a list of task-scoped result objects")
    execution = record_research_question_query_results(
        sub_hypothesis,
        [dict(item) for item in (retrieval_results or []) if isinstance(item, dict)],
    )
    execution = {
        **dict(execution),
        "schema_version": "research_question_retrieval_execution_ledger_v3",
        "sub_hypothesis_id": normalized_sub_id,
        "recorded_at": time.time(),
    }
    contract = (
        sub_hypothesis.get("research_question_contract")
        if isinstance(sub_hypothesis.get("research_question_contract"), dict)
        else {}
    )
    contract_id = str(contract.get("contract_id") or execution.get("research_question_contract_id") or "")
    slot_coverage_summary = {
        "schema_version": "slot_coverage_ledger_v3",
        "project_id": project_id,
        "sub_hypothesis_id": normalized_sub_id,
        "research_question_contract_id": contract_id,
        "contract_revision": str(
            contract.get("contract_revision") or contract.get("declaration_hash") or ""
        ),
        "contract_hash": str(
            contract.get("declaration_hash") or contract.get("contract_revision") or ""
        ),
        "slots": dict(execution.get("slot_coverage_ledger") or {}),
        "aggregate_evidence_ready": bool(execution.get("aggregate_evidence_ready")),
        "gap_readiness": str(execution.get("evidence_coverage_status") or "EMPTY"),
        "updated_at": time.time(),
    }
    complete = str(execution.get("status") or "") == "COMPLETE"
    evidence_coverage_status = str(execution.get("evidence_coverage_status") or "EMPTY")
    workflow_state = record_workflow_status(
        project,
        stage=RESEARCH_QUESTION_RETRIEVAL_STAGE,
        status=(
            "RESEARCH_QUESTION_RETRIEVAL_RECORDED"
            if complete
            else "RESEARCH_QUESTION_RETRIEVAL_PARTIAL"
        ),
        terminal=False,
        allowed_next_stages=[TANXI_TOOL, RESEARCH_QUESTION_RETRIEVAL_STAGE],
        blocked_stages=[],
        reason_code=(
            "V3_SLOT_RETRIEVAL_EXECUTION_COMPLETE_EVIDENCE_COVERAGE_EMPTY"
            if complete and evidence_coverage_status == "EMPTY"
            else "V3_SLOT_RETRIEVAL_RECORDED_SOURCE_ASSERTIONS_STILL_REQUIRED"
            if complete
            else "V3_SLOT_RETRIEVAL_TASKS_REMAIN_UNEXECUTED"
        ),
        artifact_ids=[normalized_sub_id],
        remediation_plan={
            "kind": "source_span_extraction_and_tanxi_reaudit",
            "instruction": (
                "Import returned source documents, extract versioned source spans and explicit assertions, then rerun TanXi. "
                "Empty task results remain retrieval coverage diagnostics only."
            ),
            "unexecuted_task_ids": list(execution.get("unexecuted_task_ids") or []),
        },
    )
    result_payload = {
        "schema_version": "research_question_retrieval_application_result_v3",
        "project_id": project_id,
        "sub_hypothesis_id": normalized_sub_id,
        "retrieval_execution": execution,
        "retrieval_execution_status": str(execution.get("retrieval_execution_status") or execution.get("status") or ""),
        "candidate_intake_status": str(execution.get("candidate_intake_status") or "EMPTY"),
        "alignment_status": str(execution.get("alignment_status") or "NOT_EXECUTED"),
        "candidate_count": int(execution.get("candidate_count") or 0),
        "metadata_kept_count": int(execution.get("metadata_kept_count") or 0),
        "fulltext_available_count": int(execution.get("fulltext_available_count") or 0),
        "alignment_completed_count": int(execution.get("alignment_completed_count") or 0),
        "alignment_not_executed_count": int(execution.get("alignment_not_executed_count") or 0),
        "alignment_integrity_error_count": int(execution.get("alignment_integrity_error_count") or 0),
        "admission_status": str(execution.get("admission_status") or "EMPTY"),
        "evidence_coverage_status": evidence_coverage_status,
        "aggregate_evidence_ready": bool(execution.get("aggregate_evidence_ready")),
        "required_direct_slot_ids": list(execution.get("required_direct_slot_ids") or []),
        "covered_direct_slot_ids": list(execution.get("covered_direct_slot_ids") or []),
        "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
        "direct_evidence_paper_count": int(execution.get("direct_evidence_paper_count") or 0),
        "slot_coverage_ledger": dict(execution.get("slot_coverage_ledger") or {}),
        "scientific_gap_verdict": "PROHIBITED",
        **workflow_state,
    }
    record_workflow_execution(
        project,
        RESEARCH_QUESTION_RETRIEVAL_STAGE,
        tool_input,
        result_payload,
        execution_key=str(gate.get("execution_key") or ""),
    )
    manager.persist_v3_retrieval_execution(
        project_id,
        sub_hypothesis_id=normalized_sub_id,
        execution=execution,
        field_updates={
            "research_workflow_control": project.get("research_workflow_control") or {},
            "slot_coverage_summary_v2": {
                "schema_version": "slot_coverage_summary_v2",
                "sub_hypothesis_id": normalized_sub_id,
                "summary": slot_coverage_summary,
                "updated_at": time.time(),
            },
        },
    )
    log_event(
        "SCIENCE",
        "research_question_slot_retrieval_recorded",
        project_id=project_id,
        sub_hypothesis_id=normalized_sub_id,
        status=str(execution.get("status") or ""),
        executed_task_count=len(execution.get("results") or []),
        unexecuted_task_count=len(execution.get("unexecuted_task_ids") or []),
        required_direct_slot_count=len(execution.get("required_direct_slot_ids") or []),
        covered_direct_slot_count=len(execution.get("covered_direct_slot_ids") or []),
        missing_direct_slot_count=len(execution.get("missing_direct_slot_ids") or []),
        direct_evidence_paper_count=int(execution.get("direct_evidence_paper_count") or 0),
        slot_policy_verdicts={
            str(slot): str(item.get("policy_verdict") or "")
            for slot, item in (execution.get("slot_coverage_ledger") or {}).items()
            if isinstance(item, dict)
        },
    )
    return json.dumps(result_payload, ensure_ascii=False, indent=2)


def synchronize_tanxi_ranked_gaps(
    canonical_gaps: Any,
    ranked_gaps: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Persist only current v2, source-bound candidate artifacts.

    The canonical list is an audit ledger, not a primary-mechanism pool.  It
    deliberately retains each routed v2 candidate so retrieval and package
    decisions can be traced without reusing historical candidate schemas.
    """
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source in (ranked_gaps,):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            gap_id = str(item.get("gap_id") or "").strip()
            if not gap_id or gap_id in seen_ids:
                continue
            try:
                assessment = assessment_of(item)
            except ValueError:
                continue
            if assessment.get("route") not in {item.value for item in GapRoute}:
                continue
            seen_ids.add(gap_id)
            merged.append(_compact_tanxi_ranked_gap(item))
    return dedupe_causal_identity_gaps(merged)[: max(1, int(limit or 10))]


def gap_record_is_foundational_bridge(record: dict[str, Any]) -> bool:
    assessment = record.get("foundational_bridge_assessment") if isinstance(record.get("foundational_bridge_assessment"), dict) else {}
    import_context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    return bool(
        assessment.get("research_role") == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or assessment.get("direct_target_evidence") is False and assessment
        or str(record.get("research_role") or "").upper() == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or str(record.get("stratified_layer") or import_context.get("stratified_layer") or "") == "L1_milestone"
    )


def build_source_alignment_verdict(
    gap: dict[str, Any],
    role_results: list[dict[str, Any]],
    *,
    contract_available: bool,
    verified: bool,
    contextual_role_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    roles = [str(item.get("source_role") or "unresolved") for item in role_results]
    contextual_roles = [
        str(item.get("source_role") or "unresolved")
        for item in (contextual_role_results or [])
        if isinstance(item, dict)
    ]
    effective_context_roles = contextual_roles or roles
    supported_fields = {
        str(field)
        for item in role_results
        for field in (item.get("causal_fields_supported") or [])
        if str(field)
    }
    identities = [
        item.get("source_identity")
        for item in ((contextual_role_results or []) or role_results)
        if isinstance(item.get("source_identity"), dict)
    ]
    fully_project_outside = bool(identities) and all(bool(identity.get("fully_project_outside")) for identity in identities)
    if not contract_available or not verified or not role_results:
        verdict = "UNVERIFIABLE_SOURCE"
        reason = "The original fragment lacks a verifiable paper-qualified source unit or sub-hypothesis alignment contract."
    elif effective_context_roles and all(role == "out_of_scope" for role in effective_context_roles):
        verdict = "OUT_OF_SCOPE"
        reason = "The complete contextual source evidence set cannot establish the current project/sub-hypothesis object."
    elif contextual_roles and any(role in {"direct", "partial"} for role in contextual_roles):
        verdict = "PARTIALLY_ALIGNED"
        reason = (
            "Adjacent same-paper context establishes the scientific object and causal roles, "
            "while the immutable gap-predicate fragment itself remains incomplete."
        )
    elif roles and all(role == "rationale_only" for role in roles):
        verdict = "RATIONALE_ALIGNED"
        reason = "The source is aligned only as review/background/foundational rationale."
    elif "direct" in roles or (
        str(gap.get("gap_type") or "") == "causal_mediation_unresolved"
        and {"input", "mediator", "outcome"}.issubset(supported_fields)
        and all(role in {"direct", "partial"} for role in roles)
    ) or (
        str(gap.get("gap_type") or "") in {"contradiction", "theory_observation_mismatch"}
        and {"input", "outcome"}.issubset(supported_fields)
        and all(role in {"direct", "partial"} for role in roles)
    ) or (
        str(gap.get("gap_type") or "") == "implicit_tabi"
        and str((gap.get("composite_evidence_contract") or {}).get("status") or "") == "PASSED"
        and (
            {"input", "outcome"}.issubset(supported_fields)
            or {"input", "mediator", "outcome"}.issubset(supported_fields)
        )
        and all(role in {"direct", "partial"} for role in roles)
    ):
        verdict = "DIRECTLY_ALIGNED"
        reason = "The original bounded source evidence supports the current project object, sub-hypothesis, process, and target outcome."
    elif any(role == "partial" for role in roles):
        verdict = "PARTIALLY_ALIGNED"
        reason = "The original source is project- and sub-hypothesis-aligned but does not support the complete object-process-outcome identity."
    else:
        verdict = "RATIONALE_ALIGNED"
        reason = "The source supports background context but not a direct causal object-process-outcome fragment."
    return {
        "version": "source_alignment_verdict_v1",
        "verdict": verdict,
        "passes_for_direct": verdict == "DIRECTLY_ALIGNED",
        "contract_available": contract_available,
        "source_units_verified": verified,
        "source_roles": role_results,
        "contextual_source_roles": list(contextual_role_results or []),
        "supported_causal_fields": sorted(supported_fields),
        "fully_project_outside": fully_project_outside,
        "reason": reason,
    }


def build_gap_epistemic_verdict(gap: dict[str, Any]) -> dict[str, Any]:
    gap_type = str(gap.get("gap_type") or "")
    audit = gap.get("gap_epistemic_audit") if isinstance(gap.get("gap_epistemic_audit"), dict) else {}
    source_text = " ".join(
        str(value or "")
        for value in (
            (gap.get("gap_signal") or {}).get("text") if isinstance(gap.get("gap_signal"), dict) else "",
            (gap.get("mechanism_issue_signal") or {}).get("source_text") if isinstance(gap.get("mechanism_issue_signal"), dict) else "",
            ((gap.get("causal_gap") or {}).get("explicit_source_gap") or {}).get("text")
            if isinstance((gap.get("causal_gap") or {}).get("explicit_source_gap"), dict) else "",
            (gap.get("reasoning_signal") or {}).get("source_text")
            if isinstance(gap.get("reasoning_signal"), dict) else "",
            *(
                str(item.get("excerpt") or "")
                for item in (gap.get("source_evidence_units") or [])
                if isinstance(item, dict)
            ),
        )
    )
    predicate = explicit_gap_predicate_assessment(source_text)
    source_units = [
        item for item in (gap.get("source_evidence_units") or [])
        if isinstance(item, dict)
    ]
    verified_source_units = [
        item for item in source_units
        if item.get("paper_id") and item.get("source_unit_id")
        and item.get("binding_status") == "SOURCE_UNIT_VERIFIED"
    ]
    reasoning_signal = gap.get("reasoning_signal") if isinstance(gap.get("reasoning_signal"), dict) else {}
    comparability = (
        reasoning_signal.get("comparability_contract")
        if isinstance(reasoning_signal.get("comparability_contract"), dict)
        else {}
    )
    mismatch_comparison = (
        reasoning_signal.get("comparison_contract")
        if isinstance(reasoning_signal.get("comparison_contract"), dict)
        else {}
    )
    mediation = gap.get("causal_mediation") if isinstance(gap.get("causal_mediation"), dict) else {}
    composite_contract = (
        gap.get("composite_evidence_contract")
        if isinstance(gap.get("composite_evidence_contract"), dict)
        else {}
    )
    if not composite_contract and predicate.get("passes") and verified_source_units:
        composite_contract = build_composite_evidence_contract(
            "EXPLICIT_AUTHOR_STATED_GAP",
            verified_source_units,
            scientific_contract={"explicit_gap_predicate": True},
            required_checks={"explicit_gap_predicate": True},
        )
    mediation_known = mediation.get("known") if isinstance(mediation.get("known"), dict) else {}
    context_compatibility = (
        mediation.get("context_compatibility")
        if isinstance(mediation.get("context_compatibility"), dict)
        else {}
    )
    if (
        str(gap.get("gap_candidate_pool") or "") == EVIDENCE_EXTRACTION_SHORTAGE_POOL
        or gap_type in {"evidence_extraction_shortage", "causal_evidence_missing"}
        or str(audit.get("verdict") or "") == "EVIDENCE_EXTRACTION_SHORTAGE"
    ):
        verdict = "EVIDENCE_EXTRACTION_SHORTAGE"
    elif (
        gap_type == "contradiction"
        and bool(audit.get("passes"))
        and composite_contract.get("contract_type") == "CONTRADICTION"
        and composite_contract.get("status") == "PASSED"
        and bool(comparability.get("passes"))
        and len({str(item.get("paper_id")) for item in verified_source_units}) >= 2
    ):
        verdict = "COMPOSITE_CONTRADICTION_GAP"
    elif gap_type == "contradiction":
        verdict = "EVIDENCE_EXTRACTION_SHORTAGE"
    elif (
        gap_type == "causal_mediation_unresolved"
        and bool(audit.get("passes"))
        and composite_contract.get("contract_type") == "CAUSAL_MEDIATION"
        and composite_contract.get("status") in {"PASSED", "GAP_EXISTENCE_VERIFICATION_REQUIRED"}
        and bool(context_compatibility.get("compatible"))
        and isinstance(mediation_known.get("A_to_B"), dict)
        and isinstance(mediation_known.get("B_to_C"), dict)
        and len(verified_source_units) >= 2
    ):
        verdict = "COMPOSITE_CAUSAL_MEDIATION_GAP"
    elif gap_type == "causal_mediation_unresolved":
        verdict = "EVIDENCE_EXTRACTION_SHORTAGE"
    elif (
        gap_type == "theory_observation_mismatch"
        and bool(audit.get("passes"))
        and composite_contract.get("contract_type") == "THEORY_OBSERVATION_MISMATCH"
        and composite_contract.get("status") in {"PASSED", "GAP_EXISTENCE_VERIFICATION_REQUIRED"}
        and bool(mismatch_comparison.get("passes"))
        and len({str(item.get("source_unit_id")) for item in verified_source_units}) >= 2
    ):
        verdict = "THEORY_OBSERVATION_MISMATCH"
    elif gap_type == "theory_observation_mismatch":
        verdict = "EVIDENCE_EXTRACTION_SHORTAGE"
    elif (
        gap_type == "implicit_tabi"
        and bool(audit.get("passes"))
        and composite_contract.get("contract_type") in {"TABI_CONTRADICTION", "TABI_CAUSAL_COMPOSITION"}
        and composite_contract.get("status") == "PASSED"
        and len({str(item.get("paper_id")) for item in verified_source_units}) >= 2
    ):
        verdict = "COMPOSITE_TABI_GAP"
    elif gap_type == "implicit_tabi":
        verdict = "NO_GAP_PREDICATE"
    elif (
        gap_type == "anomaly"
        and predicate.get("passes")
        and bool((gap.get("anomaly_evidence_sufficiency") or {}).get("requires_independent_corroboration"))
    ):
        verdict = "ANOMALY_CORROBORATION_REQUIRED"
    elif predicate.get("passes") and (
        predicate.get("category") == "explicit_limitation_or_failure"
        and any(marker in source_text.lower() for marker in ("fails under", "failure under", "boundary", "outside the range", "only under"))
    ):
        verdict = "BOUNDARY_CONDITION_GAP"
    elif predicate.get("passes") or bool(
        audit.get("passes") and gap_type == "causal_chain_break"
    ):
        verdict = "EXPLICIT_AUTHOR_STATED_GAP"
    else:
        verdict = "NO_GAP_PREDICATE"
    passes = verdict not in {
        "NO_GAP_PREDICATE", "EVIDENCE_EXTRACTION_SHORTAGE", "ANOMALY_CORROBORATION_REQUIRED",
    }
    return {
        "version": "gap_epistemic_verdict_v1",
        "verdict": verdict,
        "passes": passes,
        "requires_gap_existence_verification": bool(
            verdict == "ANOMALY_CORROBORATION_REQUIRED"
            or
            composite_contract.get("status") == "GAP_EXISTENCE_VERIFICATION_REQUIRED"
            or (
                passes
                and not predicate.get("passes")
                and verdict in {
                    "COMPOSITE_CONTRADICTION_GAP", "COMPOSITE_CAUSAL_MEDIATION_GAP",
                    "THEORY_OBSERVATION_MISMATCH", "COMPOSITE_TABI_GAP",
                }
            )
        ),
        "explicit_predicate_assessment": predicate,
        "source_audit": audit,
        "composite_evidence_contract": composite_contract,
        "composite_contract": (
            comparability if gap_type == "contradiction"
            else {
                "context_compatibility": context_compatibility,
                "has_A_to_B": isinstance(mediation_known.get("A_to_B"), dict),
                "has_B_to_C": isinstance(mediation_known.get("B_to_C"), dict),
            }
            if gap_type == "causal_mediation_unresolved"
            else mismatch_comparison
            if gap_type == "theory_observation_mismatch"
            else {}
        ),
        "reason": {
            "EXPLICIT_AUTHOR_STATED_GAP": "The author explicitly states that the relation is unknown, unresolved, untested, or unsupported.",
            "COMPOSITE_CONTRADICTION_GAP": "Matched source-bound claims have opposing directions under a passed comparability contract.",
            "COMPOSITE_CAUSAL_MEDIATION_GAP": "Two context-compatible source-bound causal edges establish A->B and B->C while mediation remains unresolved.",
            "THEORY_OBSERVATION_MISMATCH": "A source-bound theory/observation mismatch or anomaly is reported.",
            "COMPOSITE_TABI_GAP": "A TABI inference is backed by a passed, paper-qualified contradiction or causal-composition contract.",
            "BOUNDARY_CONDITION_GAP": "A known mechanism is explicitly reported to fail under a defined boundary condition.",
            "NO_GAP_PREDICATE": "The source discusses a scientific dimension but does not establish missing knowledge.",
            "EVIDENCE_EXTRACTION_SHORTAGE": "The missing field is an extraction/retrieval shortage, not a scientific knowledge gap.",
            "ANOMALY_CORROBORATION_REQUIRED": "The originating source explicitly reports an unexplained observation, but independent replication or boundary evidence is required before it is treated as an established scientific gap.",
        }[verdict],
    }


def _candidate_matches_source(candidate: str, excerpt: str) -> bool:
    candidate_normal = re.sub(r"\s+", " ", str(candidate or "")).strip().lower()
    excerpt_normal = re.sub(r"\s+", " ", str(excerpt or "")).strip().lower()
    if not candidate_normal or not excerpt_normal:
        return False
    if candidate_normal in excerpt_normal:
        return True
    candidate_terms = _provenance_terms(candidate_normal)
    excerpt_terms = _provenance_terms(excerpt_normal)
    return bool(len(candidate_terms & excerpt_terms) >= 2)


def _first_source_bound_candidate(
    candidates: list[Any],
    source_roles: list[dict[str, Any]],
    field: str,
) -> tuple[str, list[str]]:
    for candidate in candidates:
        rendered = re.sub(r"\s+", " ", str(candidate or "")).strip()
        if not rendered or rendered.lower() in {"unknown", "unresolved", "none", "n/a"}:
            continue
        ids = [
            str(source.get("source_unit_id") or "")
            for source in source_roles
            if field in set(source.get("causal_fields_supported") or [])
            and _candidate_matches_source(rendered, str(source.get("excerpt") or ""))
            and str(source.get("source_unit_id") or "")
        ]
        if ids:
            return rendered, list(dict.fromkeys(ids))
    return "", []


def build_causal_readiness_verdict(
    project: dict[str, Any],
    gap: dict[str, Any],
    source_alignment: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ._input_ontology import classify_input_candidate
        from ._intervention_ontology import classify_mediator_candidate
        from ._outcome_ontology import classify_outcome_candidate
        from ._research_mode import (
            COMPUTATIONAL_INTERVENTION, CONTROLLED_INTERVENTION,
            INSTRUMENTATION_OR_MEASUREMENT, LABORATORY_CONSTRAINT,
            NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
            OBSERVATIONAL_MODEL_DISCRIMINATION, THEORETICAL_OR_FORMAL,
            UNRESOLVED_RESEARCH_DESIGN, resolve_research_mode,
        )
        from ._evidence_fragment_alignment import extract_source_causal_evidence_facts
        from ._scientific_gap_gate import classify_scientific_entity, causal_entity_equivalence
    except ImportError:
        from _input_ontology import classify_input_candidate
        from _intervention_ontology import classify_mediator_candidate
        from _outcome_ontology import classify_outcome_candidate
        from _research_mode import (
            COMPUTATIONAL_INTERVENTION, CONTROLLED_INTERVENTION,
            INSTRUMENTATION_OR_MEASUREMENT, LABORATORY_CONSTRAINT,
            NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
            OBSERVATIONAL_MODEL_DISCRIMINATION, THEORETICAL_OR_FORMAL,
            UNRESOLVED_RESEARCH_DESIGN, resolve_research_mode,
        )
        from _evidence_fragment_alignment import extract_source_causal_evidence_facts
        from _scientific_gap_gate import classify_scientific_entity, causal_entity_equivalence
    branch = normalized_subhypothesis_id(
        gap.get("sub_hypothesis_id") or (gap.get("pre_rank_source_role_audit") or {}).get("sub_hypothesis_id")
    )
    subhypothesis = next(
        (
            item for item in (project.get("sub_hypotheses") or [])
            if isinstance(item, dict) and normalized_subhypothesis_id(item.get("id")) == branch
        ),
        {},
    )
    causal_chain = subhypothesis.get("causal_chain") if isinstance(subhypothesis.get("causal_chain"), list) else []
    dependent = subhypothesis.get("dependent_variables") if isinstance(subhypothesis.get("dependent_variables"), list) else []
    mediation = gap.get("causal_mediation") if isinstance(gap.get("causal_mediation"), dict) else {}
    known = mediation.get("known") if isinstance(mediation.get("known"), dict) else {}
    first_edge = known.get("A_to_B") if isinstance(known.get("A_to_B"), dict) else {}
    second_edge = known.get("B_to_C") if isinstance(known.get("B_to_C"), dict) else {}
    source_roles = [
        item for item in source_alignment.get("source_roles", [])
        if isinstance(item, dict)
    ]
    declared_role_candidates = {
        "input": [
            gap.get("intervention"), first_edge.get("source"), subhypothesis.get("independent_variable"),
            causal_chain[0] if causal_chain else "",
        ],
        "mediator": [
            gap.get("proposed_mediator"), gap.get("mechanism_hint"), first_edge.get("target"),
            causal_chain[1] if len(causal_chain) > 2 else "",
        ],
        "outcome": [
            gap.get("outcome"), second_edge.get("target"), dependent[0] if dependent else "",
            causal_chain[-1] if len(causal_chain) >= 2 else "",
        ],
    }
    # Build role candidates from bounded source text *before* reading a
    # generated gap field.  Declared values remain useful only as queries into
    # the source evidence; they are never evidence on their own.
    source_causal_evidence_facts = extract_source_causal_evidence_facts(
        source_roles,
        declared_candidates=declared_role_candidates,
    )

    def _source_fact_candidate(role: str) -> tuple[str, list[str], dict[str, Any]]:
        support_rank = {
            "SOURCE_VERIFIED_CANDIDATE": 3,
            "SOURCE_ROLE_FIELD": 2,
            "EXPLICIT_TEXT_PATTERN": 1,
        }
        candidates = [
            fact for fact in source_causal_evidence_facts
            if str(fact.get("role") or "") == role
            and str(fact.get("value") or "").strip()
            and str(fact.get("source_unit_id") or "").strip()
        ]
        if candidates:
            best = max(
                candidates,
                key=lambda fact: (
                    support_rank.get(str(fact.get("support_level") or ""), 0),
                    len(str(fact.get("value") or "")),
                ),
            )
            return (
                str(best.get("value") or "").strip(),
                [str(best.get("source_unit_id") or "")],
                dict(best),
            )
        # Compatibility fallback for source-role records created before the
        # source-causal-fact schema.  It still requires an excerpt-level role
        # declaration and source-unit match; it cannot use a subhypothesis as
        # a factual source.
        value, ids = _first_source_bound_candidate(
            declared_role_candidates[role], source_roles, role,
        )
        return value, ids, {}

    input_value, input_ids, input_fact = _source_fact_candidate("input")
    mediator_value, mediator_ids, mediator_fact = _source_fact_candidate("mediator")
    outcome_value, outcome_ids, outcome_fact = _source_fact_candidate("outcome")
    fragment_alignments = [
        {
            "paper_id": str(source.get("paper_id") or ""),
            "source_unit_id": str(source.get("source_unit_id") or ""),
            "excerpt_hash": str(source.get("excerpt_hash") or ""),
            "excerpt": str(source.get("excerpt") or ""),
            "semantic_verdict": (
                "ALIGNED_TRIADIC_EVIDENCE"
                if source.get("source_role") == "direct"
                else "ALIGNED_PARTIAL_EVIDENCE"
            ),
            "source_role": str(source.get("source_role") or ""),
            "causal_fields_supported": list(source.get("causal_fields_supported") or []),
            "object_alignment": dict(source.get("object_alignment") or {}),
            "process_alignment": dict(source.get("process_alignment") or {}),
            "outcome_alignment": dict(source.get("outcome_alignment") or {}),
        }
        for source in source_roles
        if source.get("source_role") in {"direct", "partial"}
    ]
    competing_mechanisms = [
        str(value).strip() for value in (gap.get("competing_mechanisms") or [])
        if str(value).strip()
    ]
    comparison = str(gap.get("comparison") or subhypothesis.get("comparison") or subhypothesis.get("control") or "")
    falsification = str(gap.get("falsification") or subhypothesis.get("falsification_condition") or "")
    mode_contract = {
        "input": input_value,
        "proposed_mediator": mediator_value,
        "output": outcome_value,
        "comparison": comparison,
        "falsification": falsification,
        "context": subhypothesis.get("focus") or "",
        "research_design_evidence": {
            "status": "SOURCE_BOUND" if source_alignment.get("passes_for_direct") else "UNSUPPORTED",
            "fragment_alignments": fragment_alignments,
        },
    }
    mismatch_contract = (
        (gap.get("reasoning_signal") or {}).get("comparison_contract")
        if isinstance(gap.get("reasoning_signal"), dict)
        and isinstance((gap.get("reasoning_signal") or {}).get("comparison_contract"), dict)
        else {}
    )
    if (
        str(gap.get("gap_type") or "") == "theory_observation_mismatch"
        and mismatch_contract.get("passes") is True
    ):
        # This declaration is derived from the strict matched
        # prediction--observation contract, not from a stray occurrence of
        # ``model`` or ``observed`` in one paper.
        mode_contract["declared_research_mode"] = OBSERVATIONAL_MODEL_DISCRIMINATION
    mode_resolution = resolve_research_mode(
        project,
        gap,
        mode_contract,
        {"sub_hypothesis_id": branch, **mode_contract},
    )
    mode = str(mode_resolution.get("mode") or UNRESOLVED_RESEARCH_DESIGN)
    input_assessment = classify_input_candidate(
        input_value,
        research_mode=mode,
        source_unit_ids=input_ids,
        require_source_bound=True,
    )
    mediator_assessment = classify_mediator_candidate(mediator_value)
    input_entity_type = classify_scientific_entity(input_value, role="input")
    mediator_entity_type = classify_scientific_entity(mediator_value, role="mediator")
    outcome_entity_type = classify_scientific_entity(outcome_value, role="outcome")
    mediator_outcome_equivalence = causal_entity_equivalence(mediator_value, outcome_value)
    target_outcome_terms = [
        *(str(item) for item in dependent if str(item).strip()),
        str(causal_chain[-1]) if causal_chain else "",
        *(
            str(item) for item in (
                ((project.get("subhypothesis_alignment_contracts") or {}).get(branch) or {}).get("outcome_terms") or []
            ) if str(item).strip()
        ),
    ]
    outcome_assessment = classify_outcome_candidate(
        outcome_value,
        research_mode=mode,
        target_outcome_terms=target_outcome_terms,
        source_unit_ids=outcome_ids,
        require_target_alignment=True,
        require_source_bound=True,
    )
    input_valid = bool(input_assessment.get("admissible_as_input"))
    competing_valid = bool(
        len(competing_mechanisms) >= 2
        and len({str(source.get("source_unit_id") or "") for source in source_roles if source.get("source_unit_id")}) >= 2
    )
    mediator_valid = bool(
        mediator_assessment.get("admissible_as_mediator")
        and mediator_entity_type.get("allowed_as_mediator")
        and not mediator_outcome_equivalence.get("equivalent")
        and mediator_ids
    ) or competing_valid
    outcome_valid = bool(
        outcome_assessment.get("admissible_as_outcome")
        and outcome_entity_type.get("entity_type") not in {"METHOD_TOOL", "RELATIONAL_CLAUSE", "UNKNOWN_ENTITY"}
    )
    mode_valid = mode != UNRESOLVED_RESEARCH_DESIGN
    source_ids = {
        str(source.get("source_unit_id") or "") for source in source_roles
        if str(source.get("source_unit_id") or "")
    }
    bound_ids = set(input_ids + mediator_ids + outcome_ids)
    provenance_valid = bool(
        source_alignment.get("passes_for_direct")
        and input_ids and outcome_ids
        and (mediator_ids or competing_valid)
        and bound_ids.issubset(source_ids)
    )
    failures: list[str] = []
    if not input_valid:
        failures.append("INPUT_INVALID")
    if not mediator_valid:
        failures.append("MEDIATOR_INVALID")
    if not outcome_valid:
        failures.append("OUTCOME_INVALID")
    if not mode_valid:
        failures.append("MODE_UNRESOLVED")
    if not provenance_valid:
        failures.append("SOURCE_ROLE_CONFLICT")
    verdict = failures[0] if failures else "CAUSAL_CHAIN_VALID"
    return {
        "version": "causal_readiness_verdict_v1",
        "verdict": verdict,
        "passes": verdict == "CAUSAL_CHAIN_VALID",
        "failure_verdicts": failures,
        "sub_hypothesis_id": branch,
        "research_mode": mode,
        "research_mode_resolution": mode_resolution,
        "causal_fields": {
            "input": {
                "value": input_value,
                "normalized_value": str(input_assessment.get("normalized_value") or input_value),
                "source_unit_ids": input_ids,
                "assessment": input_assessment,
                "entity_type": input_entity_type,
                "source_fact": input_fact,
            },
            "mediator": {
                "value": mediator_value,
                "source_unit_ids": mediator_ids,
                "assessment": mediator_assessment,
                "entity_type": mediator_entity_type,
                "outcome_semantic_folding": mediator_outcome_equivalence,
                "source_fact": mediator_fact,
            },
            "competing_mechanisms": competing_mechanisms,
            "outcome": {
                "value": outcome_value,
                "source_unit_ids": outcome_ids,
                "assessment": outcome_assessment,
                "entity_type": outcome_entity_type,
                "source_fact": outcome_fact,
            },
        },
        "source_causal_evidence_facts": source_causal_evidence_facts,
        "source_provenance_valid": provenance_valid,
        "reason": (
            "The original evidence supplies a source-bound input, specific mediator or competing mechanism, outcome, and resolved research mode."
            if not failures else "Causal readiness failed: " + ", ".join(failures)
        ),
    }


def _original_source_role_hash(audit: dict[str, Any]) -> str:
    payload = {key: value for key, value in audit.items() if key != "audit_hash"}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def original_source_role_audit_is_intact(audit: dict[str, Any]) -> bool:
    return bool(
        isinstance(audit, dict)
        and audit.get("immutable") is True
        and str(audit.get("audit_hash") or "")
        and str(audit.get("audit_hash")) == _original_source_role_hash(audit)
    )


def build_original_source_role_audit(
    gap: dict[str, Any],
    source: dict[str, Any],
    epistemic: dict[str, Any],
    causal: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the original source identity before any evidence enrichment."""
    existing = gap.get("original_source_role_audit") if isinstance(gap.get("original_source_role_audit"), dict) else {}
    if existing.get("immutable") is True:
        if original_source_role_audit_is_intact(existing):
            return dict(existing)
        return {
            "version": "original_source_role_v1",
            "gap_id": str(gap.get("gap_id") or ""),
            "sub_hypothesis_id": str(gap.get("sub_hypothesis_id") or ""),
            "source_clue_role": "out_of_scope",
            "source_candidate_state": "SOURCE_CANDIDATE",
            "state": "ORIGINAL_SOURCE_AUDITED",
            "allowed_transition": "REJECTED_SOURCE_AUDIT",
            "immutable": True,
            "integrity_status": "TAMPERED_OR_CORRUPT",
            "audit_hash": "",
        }
    source_roles = [item for item in source.get("source_roles", []) if isinstance(item, dict)]
    fields = causal.get("causal_fields") if isinstance(causal.get("causal_fields"), dict) else {}
    supported = set(source.get("supported_causal_fields") or [])
    identity_pass = bool(
        source_roles
        and all(bool((item.get("source_identity") or {}).get("same_sub_hypothesis")) for item in source_roles)
    )
    all_pass = bool(
        source.get("verdict") == "DIRECTLY_ALIGNED"
        and epistemic.get("passes") is True
        and causal.get("passes") is True
    )
    # Keep the three verdicts independent, then derive the final source-clue
    # role from their conjunction.  ``DIRECTLY_ALIGNED`` means that a fragment
    # discusses the right object/process/outcome; it is not yet a direct gap
    # when the fragment has no knowledge-gap predicate or lacks valid causal
    # roles.
    if source.get("verdict") == "OUT_OF_SCOPE":
        source_role = "out_of_scope"
    elif source.get("verdict") == "RATIONALE_ALIGNED" or not epistemic.get("passes"):
        source_role = "rationale_only"
    elif all_pass:
        source_role = "direct"
    else:
        source_role = "partial"
    if all_pass:
        transition = "PRIMARY_MECHANISM_CANDIDATE"
    elif source.get("verdict") == "OUT_OF_SCOPE" and source.get("fully_project_outside"):
        transition = "REJECTED_SOURCE_AUDIT"
    elif gap.get("legacy_source_status") == "LEGACY_SOURCE_UNVERIFIABLE":
        transition = "SECONDARY_RESEARCH_OPPORTUNITY"
    elif source.get("verdict") == "UNVERIFIABLE_SOURCE" or epistemic.get("verdict") == "EVIDENCE_EXTRACTION_SHORTAGE":
        transition = "EVIDENCE_EXTRACTION_SHORTAGE"
    else:
        transition = "SECONDARY_RESEARCH_OPPORTUNITY"

    def causal_role(name: str) -> dict[str, Any]:
        entry = fields.get(name) if isinstance(fields.get(name), dict) else {}
        assessment = entry.get("assessment") if isinstance(entry.get("assessment"), dict) else {}
        ids = [str(item) for item in (entry.get("source_unit_ids") or []) if str(item)]
        source_record = next(
            (item for item in source_roles if str(item.get("source_unit_id") or "") in set(ids)),
            {},
        )
        admissible_key = "admissible_as_input" if name == "input" else "admissible_as_outcome" if name == "outcome" else "admissible_as_mediator"
        valid = bool(assessment.get(admissible_key) and ids)
        competing_values = [
            str(value).strip() for value in (fields.get("competing_mechanisms") or [])
            if str(value).strip()
        ] if name == "mediator" else []
        if name == "mediator" and not valid:
            valid = bool(len(competing_values) >= 2 and len(source_roles) >= 2)
        return {
            "value": str(entry.get("value") or ""),
            "normalized_value": str(entry.get("normalized_value") or entry.get("value") or ""),
            "competing_values": competing_values,
            "verdict": "VALID" if valid else "INVALID",
            "paper_id": str(source_record.get("paper_id") or ""),
            "source_unit_id": ids[0] if ids else "",
            "source_unit_ids": ids,
            "ontology": str(assessment.get("version") or ""),
        }

    predicate = epistemic.get("explicit_predicate_assessment") if isinstance(epistemic.get("explicit_predicate_assessment"), dict) else {}
    audit = {
        "version": "original_source_role_v1",
        "gap_id": str(gap.get("gap_id") or ""),
        "sub_hypothesis_id": str(causal.get("sub_hypothesis_id") or gap.get("sub_hypothesis_id") or ""),
        "source_evidence_set": [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "source_unit_id": str(item.get("source_unit_id") or ""),
                "excerpt_hash": str(item.get("excerpt_hash") or ""),
                "source_field": str(item.get("source_field") or ""),
                "excerpt": str(item.get("excerpt") or "")[:600],
                "paper_genre": str(item.get("paper_genre") or ""),
                "claim_role": (
                    "contradiction_claim" if epistemic.get("verdict") == "COMPOSITE_CONTRADICTION_GAP"
                    else "causal_edge" if epistemic.get("verdict") == "COMPOSITE_CAUSAL_MEDIATION_GAP"
                    else "theory_or_observation_claim" if epistemic.get("verdict") == "THEORY_OBSERVATION_MISMATCH"
                    else "tabi_composite_claim" if epistemic.get("verdict") == "COMPOSITE_TABI_GAP"
                    else "gap_statement"
                ),
            }
            for item in source_roles
        ],
        "source_alignment": {
            "object": "PASS" if source_roles and all(bool((item.get("object_alignment") or {}).get("passes")) for item in source_roles) else "FAIL",
            "process": "PASS" if (
                "mediator" in supported
                or (
                    str(epistemic.get("verdict") or "")
                    in {"COMPOSITE_CONTRADICTION_GAP", "THEORY_OBSERVATION_MISMATCH", "COMPOSITE_TABI_GAP"}
                    and len(fields.get("competing_mechanisms") or []) >= 2
                )
            ) else "FAIL",
            "outcome": "PASS" if "outcome" in supported else "FAIL",
            "sub_hypothesis": "PASS" if identity_pass else "FAIL",
            "verdict": str(source.get("verdict") or "UNVERIFIABLE_SOURCE"),
        },
        "gap_epistemic_basis": {
            "verdict": str(epistemic.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
            "gap_predicate": str((predicate.get("matched_predicates") or [""])[0]),
            "gap_type": str(gap.get("gap_type") or ""),
        },
        "causal_roles": {
            "input": causal_role("input"),
            "mediator": causal_role("mediator"),
            "outcome": causal_role("outcome"),
        },
        "research_mode": str(causal.get("research_mode") or "UNRESOLVED_RESEARCH_DESIGN"),
        "source_clue_role": source_role,
        "source_candidate_state": "SOURCE_CANDIDATE",
        "state": "ORIGINAL_SOURCE_AUDITED",
        "allowed_transition": transition,
        "immutable": True,
        "integrity_status": "VERIFIED",
    }
    audit["audit_hash"] = _original_source_role_hash(audit)
    return audit


def mark_restricted_component_bridge_hypothesis_policy(gap: dict[str, Any]) -> dict[str, Any]:
    """Mark a component-bridge gap as hypothesis-usable only under a capped track.

    This is deliberately separate from the primary scientific-gap route:
    Component/bridge evidence may motivate a scoped bridge hypothesis.  It is
    a distinct route from the primary-mechanism budget and always carries a
    final-object claim disclaimer, but lack of direct-core evidence must not
    prevent the draft -> Socrates -> debate sequence from running.
    """
    item = gap if isinstance(gap, dict) else {}
    if item.get("restricted_bridge_role_contract_ready") is False:
        missing_roles = list(
            (
                item.get("restricted_bridge_role_contract")
                if isinstance(item.get("restricted_bridge_role_contract"), dict)
                else {}
            ).get("missing_roles")
            or []
        )
        item["gap_candidate_pool"] = EVIDENCE_EXTRACTION_SHORTAGE_POOL
        item["gap_track"] = "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED"
        item["scientific_state"] = "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED"
        item["component_bridge_context_ready"] = True
        item["component_bridge_gap_synthesis_ready"] = False
        item["eligible_for_hypothesis_generation"] = False
        item["eligible_for_restricted_bridge_hypothesis"] = False
        item["restricted_component_bridge_hypothesis_allowed"] = False
        item["hypothesis_generation_track"] = "restricted_component_bridge_repair"
        item["hypothesis_package_type"] = ""
        readiness = item.get("hypothesis_readiness") if isinstance(item.get("hypothesis_readiness"), dict) else {}
        item["hypothesis_readiness"] = {
            **readiness,
            "status": "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED",
            "ready_for_hypothesis_generation": False,
            "restricted_component_bridge": True,
            "missing_roles": missing_roles,
        }
        return item
    item["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
    item["gap_track"] = "COMPONENT_BRIDGE_GAP_SYNTHESIS"
    item["scientific_state"] = "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY"
    item["component_bridge_gap_synthesis_ready"] = True
    item["eligible_for_hypothesis_generation"] = False
    item["eligible_for_restricted_bridge_hypothesis"] = True
    item["restricted_component_bridge_hypothesis_allowed"] = True
    item["hypothesis_generation_track"] = "restricted_component_bridge"
    item["hypothesis_package_type"] = "restricted_component_bridge"
    item["primary_eligible"] = False
    item["core_eligible"] = False
    item["standard_core_eligible"] = False
    item["direct_core"] = False
    item["direct_core_evidence_allowed"] = False
    item["may_support_final_object_claim"] = False
    item["may_fill_primary_evidence_slots"] = False
    item["claim_strength_cap"] = "no_final_object_claim_validation"
    item["claim_strength_effect"] = "no_final_object_claim_validation"
    # Direct core is an evidence classification, not an admission gate for
    # this route.  Socrates enriches the *draft* after MingLi has made the
    # bridge hypothesis explicit.
    item["post_draft_socrates_enrichment_required"] = True
    item["final_object_claim_disclaimer"] = (
        "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。"
    )
    item["requires_human_review"] = True
    forbidden = [
        str(value)
        for value in (item.get("forbidden_claims") if isinstance(item.get("forbidden_claims"), list) else [])
        if str(value)
    ]
    for claim in (
        "Do not state that the final object has been directly validated.",
    ):
        if claim not in forbidden:
            forbidden.append(claim)
    item["forbidden_claims"] = forbidden
    qualification = item.get("alignment_qualification") if isinstance(item.get("alignment_qualification"), dict) else {}
    item["alignment_qualification"] = {
        **qualification,
        "primary_eligible": False,
        "component_bridge_gap_synthesis_ready": True,
        "restricted_component_bridge_hypothesis_allowed": True,
        "direct_core": False,
        "standard_core_eligible": False,
        "core_eligible": False,
        "may_support_final_object_claim": False,
        "claim_strength_cap": "no_final_object_claim_validation",
        "post_draft_socrates_enrichment_required": True,
        "final_object_claim_disclaimer": item["final_object_claim_disclaimer"],
        "sub_hypothesis_id": str(item.get("sub_hypothesis_id") or qualification.get("sub_hypothesis_id") or ""),
        "reason": "Restricted component-bridge gap; draft first, then Socrates enrichment with a final-object claim disclaimer.",
    }
    readiness = item.get("hypothesis_readiness") if isinstance(item.get("hypothesis_readiness"), dict) else {}
    item["hypothesis_readiness"] = {
        **readiness,
        "status": "READY_FOR_RESTRICTED_BRIDGE_HYPOTHESIS",
        "ready_for_hypothesis_generation": True,
        "primary_eligible": False,
        "restricted_component_bridge": True,
        "claim_strength_cap": "no_final_object_claim_validation",
        "post_draft_socrates_enrichment_required": True,
        "final_object_claim_disclaimer": item["final_object_claim_disclaimer"],
    }
    return item


def apply_three_verdict_gap_route(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    item = dict(gap)
    if str(item.get("gap_type") or "") == "component_bridge_gap_synthesis":
        branch = infer_gap_subhypothesis_id(item, project)
        if branch:
            item["sub_hypothesis_id"] = branch
        source_units = [
            unit for unit in (item.get("source_evidence_units") or [])
            if isinstance(unit, dict)
        ]
        if not isinstance(item.get("restricted_bridge_role_contract"), dict):
            _attach_restricted_component_bridge_role_contract(
                item,
                _declared_subhypothesis_bridge_role_contract(
                    project,
                    branch or item.get("sub_hypothesis_id"),
                    source_units=source_units,
                ),
            )
        else:
            _attach_restricted_component_bridge_role_contract(
                item,
                item.get("restricted_bridge_role_contract"),
            )
        role_ready = bool(item.get("restricted_bridge_role_contract_ready"))
        item["source_alignment_verdict"] = {
            "version": "source_alignment_verdict_v1",
            "verdict": "COMPONENT_BRIDGE_CONTEXT_BOUND",
            "passes_for_direct": False,
            "passes_for_restricted_component_bridge_gap": role_ready,
            "source_roles": [
                {
                    "paper_id": str(unit.get("paper_id") or ""),
                    "source_unit_id": str(unit.get("source_unit_id") or ""),
                    "source_role": "component_bridge_context",
                    "semantic_verdict": "CONTEXT_BOUND_NONCORE_EVIDENCE",
                }
                for unit in source_units
            ],
            "fully_project_outside": False,
            "reason": (
                "The candidate is a restricted component/bridge synthesis gap: "
                "source units can establish context, but cannot directly validate "
                "the final object."
            ),
        }
        item["gap_epistemic_verdict"] = {
            "version": "gap_epistemic_verdict_v1",
            "passes": True,
            "verdict": "COMPONENT_BRIDGE_CONTEXT_WITHOUT_FINAL_DIRECT_CORE_VALIDATION",
            "category": "component_bridge_gap_synthesis",
            "requires_gap_existence_verification": False,
        }
        item["original_source_role_audit"] = {
            "version": "original_source_role_audit_v1",
            "sub_hypothesis_id": branch,
            "source_clue_role": "component_bridge_context",
            "allowed_transition": (
                "COMPONENT_BRIDGE_GAP_SYNTHESIS"
                if role_ready else "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR"
            ),
            "state": "ORIGINAL_SOURCE_AUDITED",
            "immutable": True,
            "integrity_status": "VERIFIED",
        }
        causal = item.get("causal_readiness_verdict") if isinstance(item.get("causal_readiness_verdict"), dict) else {}
        item["scientific_verdicts"] = {
            "source_alignment_verdict": "COMPONENT_BRIDGE_CONTEXT_BOUND",
            "gap_epistemic_verdict": "COMPONENT_BRIDGE_CONTEXT_WITHOUT_FINAL_DIRECT_CORE_VALIDATION",
            "causal_readiness_verdict": str(causal.get("verdict") or ""),
            "all_primary_prerequisites_pass": False,
            "restricted_component_bridge_gap": role_ready,
        }
        item["source_clue_role"] = "component_bridge_context"
        item["source_state"] = "ORIGINAL_SOURCE_AUDITED"
        item["socrates_targeted_retrieval_allowed"] = False
        item["direct_core_evidence_allowed"] = False
        item["claim_strength_effect"] = "no_final_object_claim_validation"
        if role_ready:
            item["scientific_state"] = "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY"
            item["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
            mark_restricted_component_bridge_hypothesis_policy(item)
        item["pre_rank_source_role_audit"] = {
            "status": (
                "COMPONENT_BRIDGE_CONTEXT_BOUND"
                if role_ready else "COMPONENT_BRIDGE_ROLE_CONTRACT_REPAIR_REQUIRED"
            ),
            "sub_hypothesis_id": branch,
            "source_roles": item["source_alignment_verdict"]["source_roles"],
            "socrates_targeted_retrieval_allowed": False,
            "three_verdict_route": (
                COMPOSITE_GAP_AUDIT_POOL
                if role_ready else EVIDENCE_EXTRACTION_SHORTAGE_POOL
            ),
        }
        item["pre_rank_semantic_route"] = {
            "pool": (
                COMPOSITE_GAP_AUDIT_POOL
                if role_ready else EVIDENCE_EXTRACTION_SHORTAGE_POOL
            ),
            "source_clue_role": "component_bridge_context",
            "socrates_targeted_retrieval_allowed": False,
            "reason": (
                "Restricted component-bridge gap has a materialized role contract."
                if role_ready else
                "Component-bridge context exists, but input/mediator/outcome/comparison role contract is incomplete."
            ),
        }
        return item
    source = item.get("source_alignment_verdict") if isinstance(item.get("source_alignment_verdict"), dict) else {
        "verdict": "UNVERIFIABLE_SOURCE", "passes_for_direct": False, "fully_project_outside": False,
    }
    epistemic = build_gap_epistemic_verdict(item)
    causal = build_causal_readiness_verdict(project, item, source)
    original_audit = build_original_source_role_audit(item, source, epistemic, causal)
    all_pass = bool(
        original_source_role_audit_is_intact(original_audit)
        and original_audit.get("allowed_transition") == "PRIMARY_MECHANISM_CANDIDATE"
    )
    clue_role = str(original_audit.get("source_clue_role") or "partial")
    if all_pass:
        pool = PRIMARY_MECHANISM_CANDIDATE_POOL
        # The original fragment has established a concrete causal identity,
        # but Socrates authority is decided only after the direct-evidence
        # lanes are audited below.  No-search-needed and targeted-repair are
        # not distinguishable at this stage.
        targeted = False
        scientific_state = "PRIMARY_MECHANISM_CANDIDATE"
    elif source.get("verdict") == "OUT_OF_SCOPE" and source.get("fully_project_outside"):
        pool = REJECTED_EVIDENCE_AUDIT_POOL
        targeted = False
        scientific_state = "REJECTED_SOURCE_AUDIT"
    elif source.get("verdict") == "OUT_OF_SCOPE":
        pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        targeted = False
        scientific_state = "SECONDARY_RESEARCH_OPPORTUNITY"
    elif item.get("legacy_source_status") == "LEGACY_SOURCE_UNVERIFIABLE":
        pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        targeted = False
        scientific_state = "SECONDARY_RESEARCH_OPPORTUNITY"
    elif source.get("verdict") == "UNVERIFIABLE_SOURCE" or epistemic.get("verdict") == "EVIDENCE_EXTRACTION_SHORTAGE":
        pool = EVIDENCE_EXTRACTION_SHORTAGE_POOL
        targeted = False
        scientific_state = "EVIDENCE_EXTRACTION_SHORTAGE"
    elif source.get("verdict") == "RATIONALE_ALIGNED" or not epistemic.get("passes"):
        pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        targeted = False
        scientific_state = "SECONDARY_RESEARCH_OPPORTUNITY"
    elif epistemic.get("passes") is True and causal.get("passes") is not True:
        # Gap existence and causal readiness answer different questions.  An
        # author-stated unknown, matched contradiction, or bounded anomaly is
        # retained as a scientific result even when the original literature
        # has not yet supplied a source-bound I/M/O research contract.  This
        # state must never be promoted directly to a mechanism hypothesis.
        pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        targeted = False
        scientific_state = "KNOWN_GAP_NOT_CAUSALLY_READY"
    else:
        # A real, aligned scientific question without a complete original
        # causal identity is intentionally secondary.  Socrates must not run
        # a generic search to invent its input, mechanism, or outcome.
        pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
        targeted = False
        scientific_state = "SECONDARY_RESEARCH_OPPORTUNITY"
    item["gap_epistemic_verdict"] = epistemic
    item["causal_readiness_verdict"] = causal
    item["original_source_role_audit"] = original_audit
    # Keep the detailed verdict payloads once at top level.  This compact
    # index is what downstream gates normally inspect, avoiding three large
    # copies of the same source excerpts in persisted project JSON.
    item["scientific_verdicts"] = {
        "source_alignment_verdict": str(source.get("verdict") or "UNVERIFIABLE_SOURCE"),
        "gap_epistemic_verdict": str(epistemic.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
        "causal_readiness_verdict": str(causal.get("verdict") or "SOURCE_ROLE_CONFLICT"),
        "all_primary_prerequisites_pass": all_pass,
        "gap_existence_passes": epistemic.get("passes") is True,
        "causal_readiness_passes": causal.get("passes") is True,
    }
    item["source_clue_role"] = clue_role
    item["source_state"] = "ORIGINAL_SOURCE_AUDITED"
    item["scientific_state"] = scientific_state
    item["gap_candidate_pool"] = pool
    item["socrates_targeted_retrieval_allowed"] = targeted
    item["extraction_repair_route"] = (
        {
            "state": "EVIDENCE_EXTRACTION_SHORTAGE",
            "eligible_for_socrates": False,
            "repair_owner": "ZhiZhi",
            "repair_actions": ["resolve_paper_source_unit", "repair_pdf_or_full_text_extraction"],
            "next_transition": "SOURCE_CANDIDATE",
        }
        if pool == EVIDENCE_EXTRACTION_SHORTAGE_POOL
        else {}
    )
    pre_rank_audit = dict(item.get("pre_rank_source_role_audit") or {})
    pre_rank_audit["socrates_targeted_retrieval_allowed"] = targeted
    pre_rank_audit["final_source_clue_role"] = clue_role
    pre_rank_audit["three_verdict_route"] = pool
    item["pre_rank_source_role_audit"] = pre_rank_audit
    item["pre_rank_semantic_route"] = {
        "pool": pool,
        "source_clue_role": clue_role,
        "socrates_targeted_retrieval_allowed": targeted,
        "reason": (
            "All three independent scientific verdicts passed."
            if all_pass
            else "Primary routing blocked by: " + ", ".join(
                part for part in (
                    "source_alignment=" + str(source.get("verdict") or ""),
                    "gap_epistemic=" + str(epistemic.get("verdict") or ""),
                    "causal_readiness=" + str(causal.get("verdict") or ""),
                )
            )
        ),
    }
    return item


def build_tanxi_mechanism_draft(
    gap: dict[str, Any],
    original_source_role_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy, but never reinterpret, the audited original causal roles.

    The explicit assessment argument is used by the live TanXi pipeline.
    Reading the persisted copy from ``gap`` remains available only for legacy
    callers and migration tests; neither path infers fields from method,
    scenario, benchmark, or unrelated graph edges.
    """
    verdicts = gap.get("scientific_verdicts") if isinstance(gap.get("scientific_verdicts"), dict) else {}
    source_verdict = gap.get("source_alignment_verdict") if isinstance(gap.get("source_alignment_verdict"), dict) else {}
    epistemic_verdict = gap.get("gap_epistemic_verdict") if isinstance(gap.get("gap_epistemic_verdict"), dict) else {}
    causal_verdict = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    fields = causal_verdict.get("causal_fields") if isinstance(causal_verdict.get("causal_fields"), dict) else {}
    input_field = fields.get("input") if isinstance(fields.get("input"), dict) else {}
    mediator_field = fields.get("mediator") if isinstance(fields.get("mediator"), dict) else {}
    outcome_field = fields.get("outcome") if isinstance(fields.get("outcome"), dict) else {}
    audit = gap.get("original_source_role_audit") if isinstance(gap.get("original_source_role_audit"), dict) else {}
    handoff = (
        original_source_role_assessment
        if isinstance(original_source_role_assessment, dict)
        else gap.get("original_source_role_assessment")
        if isinstance(gap.get("original_source_role_assessment"), dict)
        else {}
    )
    all_pass = bool(
        original_source_role_audit_is_intact(audit)
        and audit.get("allowed_transition") == "PRIMARY_MECHANISM_CANDIDATE"
    )
    role = str(audit.get("source_clue_role") or gap.get("source_clue_role") or "rationale_only").strip().lower()
    handoff_conflict = bool(
        handoff
        and (
            str(handoff.get("state") or "") != "ORIGINAL_SOURCE_AUDITED"
            or str(handoff.get("source_clue_role") or "") != role
            or str(handoff.get("original_source_role_audit_hash") or "") != str(audit.get("audit_hash") or "")
        )
    )
    if handoff_conflict:
        all_pass = False
        role = "out_of_scope"
    source_units = [item for item in gap.get("source_evidence_units", []) if isinstance(item, dict)]
    issue = gap.get("mechanism_issue_signal") if isinstance(gap.get("mechanism_issue_signal"), dict) else {}
    signal = gap.get("gap_signal") if isinstance(gap.get("gap_signal"), dict) else {}
    candidate_clue = str(
        issue.get("source_text")
        or signal.get("text")
        or next((item.get("excerpt") for item in source_units if item.get("excerpt")), "")
        or ""
    ).strip()
    input_value = str(input_field.get("value") or "unresolved")
    mediator_value = str(mediator_field.get("value") or "unresolved")
    outcome_value = str(outcome_field.get("value") or "unresolved")
    seed_contract = (
        gap.get("mechanism_seed_contract")
        if isinstance(gap.get("mechanism_seed_contract"), dict)
        else {}
    )
    seed_fields = seed_contract.get("mechanism_seed") if isinstance(seed_contract.get("mechanism_seed"), dict) else {}
    seed_complete = str(seed_contract.get("status") or "") == "COMPLETE_COMPOSITE_MECHANISM_SEED"
    if seed_complete:
        input_value = str((seed_fields.get("input") or {}).get("value") or input_value)
        mediator_value = str((seed_fields.get("mediator") or {}).get("value") or mediator_value)
        outcome_value = str((seed_fields.get("outcome") or {}).get("value") or outcome_value)
    competing_mechanisms = list(fields.get("competing_mechanisms") or [])
    unresolved_core = [
        field for field, valid in (
            ("input", bool(
                input_field.get("value") and input_field.get("source_unit_ids")
                or seed_complete and (seed_fields.get("input") or {}).get("fragment_refs")
            )),
            ("mediator_or_competing_mechanism", bool(
                mediator_field.get("value") and mediator_field.get("source_unit_ids")
                or seed_complete and (seed_fields.get("mediator") or {}).get("fragment_refs")
                or len(competing_mechanisms) >= 2
            )),
            ("outcome", bool(
                outcome_field.get("value") and outcome_field.get("source_unit_ids")
                or seed_complete and (seed_fields.get("outcome") or {}).get("fragment_refs")
            )),
            ("research_mode", bool(causal_verdict.get("research_mode") and causal_verdict.get("research_mode") != "UNRESOLVED_RESEARCH_DESIGN")),
        )
        if not valid
    ]
    return {
        "gap_id": str(gap.get("gap_id") or ""),
        "input": input_value,
        "normalized_input": str(input_field.get("normalized_value") or input_value),
        "proposed_mediator": mediator_value,
        "output": outcome_value,
        "source_clue": candidate_clue,
        "source_clue_role": role,
        "source_alignment_verdict": str(source_verdict.get("verdict") or "UNVERIFIABLE_SOURCE"),
        "gap_epistemic_verdict": str(epistemic_verdict.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
        "causal_readiness_verdict": str(causal_verdict.get("verdict") or "SOURCE_ROLE_CONFLICT"),
        "input_role_assessment": dict(input_field.get("assessment") or {}),
        "mediator_role_assessments": [dict(mediator_field.get("assessment") or {})] if mediator_field else [],
        "output_role_assessment": dict(outcome_field.get("assessment") or {}),
        "causal_field_provenance": {
            "input": list(
                input_field.get("source_unit_ids")
                or (seed_fields.get("input") or {}).get("fragment_refs")
                or []
            ),
            "mediator": list(
                mediator_field.get("source_unit_ids")
                or (seed_fields.get("mediator") or {}).get("fragment_refs")
                or []
            ),
            "outcome": list(
                outcome_field.get("source_unit_ids")
                or (seed_fields.get("outcome") or {}).get("fragment_refs")
                or []
            ),
        },
        "mechanism_seed_contract": seed_contract,
        "competing_mechanisms": competing_mechanisms,
        "research_mode": str(causal_verdict.get("research_mode") or "UNRESOLVED_RESEARCH_DESIGN"),
        "original_source_role_audit_ref": {
            "version": str(audit.get("version") or ""),
            "audit_hash": str(audit.get("audit_hash") or ""),
            "immutable": audit.get("immutable") is True,
            "allowed_transition": str(audit.get("allowed_transition") or ""),
        },
        "original_source_role_handoff": {
            "version": str(handoff.get("version") or ""),
            "state": str(handoff.get("state") or ""),
            "valid": bool(handoff and not handoff_conflict),
        },
        "unresolved_fields": unresolved_core,
        "status": (
            "draft_source_roles_valid" if all_pass
            else "composite_mechanism_seed_valid" if seed_complete
            else "secondary_original_roles_incomplete"
        ),
    }

def _assess_contextual_source_units(
    project: dict[str, Any],
    source_units: list[dict[str, Any]],
    contract: dict[str, Any],
    branch: str,
    records: dict[str, dict[str, Any]],
    core_record_ids: set[str],
) -> list[dict[str, Any]]:
    """Assess adjacent context without mutating the predicate fragment role."""
    if _project_uses_research_question_evidence_v3(project) or not contract:
        return []
    try:
        from ._evidence_fragment_alignment import assess_evidence_fragment_alignment
    except ImportError:
        from _evidence_fragment_alignment import assess_evidence_fragment_alignment
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in source_units:
        source_unit_id = str(source.get("source_unit_id") or "")
        if not source_unit_id or source_unit_id in seen:
            continue
        seen.add(source_unit_id)
        excerpt = str(source.get("excerpt") or "").strip()
        record = records.get(str(source.get("paper_id") or ""), {})
        if not excerpt:
            continue
        synthetic = {
            "paper_id": str(source.get("paper_id") or ""),
            "full_text_excerpt": excerpt,
            "paper_genre": dict(record.get("paper_genre") or {}) if isinstance(record.get("paper_genre"), dict) else {},
            "publication_type": str(record.get("publication_type") or ""),
        }
        # Contextual units are intentionally adjacent same-paper windows that
        # re-anchor a clipped predicate fragment without mutating it.  Assess
        # them with a small multi-sentence window so an object sentence plus a
        # neighboring causal-axis sentence can establish a *partial* source
        # role for gap routing.  The original predicate fragment above remains
        # audited separately with its own bounded source unit, so this cannot
        # promote a clipped limitation into direct core evidence.
        alignments = assess_evidence_fragment_alignment(synthetic, contract, window_size=3, use_llm=False)
        best = max(
            alignments,
            key=lambda alignment: (
                {"direct": 3, "partial": 2, "rationale_only": 1, "out_of_scope": 0}.get(
                    str(alignment.get("source_role") or ""), -1
                ),
                len(alignment.get("causal_fields_supported") or []),
                float(alignment.get("confidence") or 0.0),
            ),
            default={},
        )
        paper_id = str(source.get("paper_id") or "")
        source_is_core = paper_id in core_record_ids or not bool(project.get("subhypothesis_alignment_contracts"))
        source_branch = next(iter(_record_subhypothesis_ids_for_aggregation(record)), "")
        same_branch = bool(branch and source_branch and branch == source_branch)
        boundary_record = str(record.get("retrieval_phase") or "") == "boundary_extension"
        foundation = gap_record_is_foundational_bridge(record)
        domain_verdict = str(record.get("domain_review_verdict") or "keep").lower()
        fully_project_outside = bool(not source_is_core or domain_verdict == "reject")
        identity_valid = bool(
            source_is_core and same_branch and not boundary_record and not foundation
            and domain_verdict not in {"review", "reject"}
        )
        source_role = (
            "rationale_only" if foundation
            else str(best.get("source_role") or "unresolved") if identity_valid
            else "out_of_scope"
        )
        results.append({
            "paper_id": paper_id,
            "source_unit_id": source_unit_id,
            "excerpt_hash": str(source.get("excerpt_hash") or ""),
            "binding_status": str(source.get("binding_status") or ""),
            "excerpt": excerpt[:1200],
            "source_field": str(source.get("source_field") or ""),
            "paper_genre": str((record.get("paper_genre") or {}).get("genre") or record.get("publication_type") or "")
            if isinstance(record.get("paper_genre"), dict)
            else str(record.get("paper_genre") or record.get("publication_type") or ""),
            "source_role": source_role,
            "semantic_verdict": (
                "FOUNDATIONAL_BRIDGE_RATIONALE_ONLY" if foundation
                else str(best.get("semantic_verdict") or "UNRESOLVED") if identity_valid
                else "SOURCE_IDENTITY_NOT_ELIGIBLE"
            ),
            "causal_fields_supported": list(best.get("causal_fields_supported") or []),
            "object_alignment": dict(best.get("object_alignment") or {}),
            "input_alignment": dict(best.get("input_alignment") or {}),
            "process_alignment": dict(best.get("process_alignment") or {}),
            "outcome_alignment": dict(best.get("outcome_alignment") or {}),
            "source_identity": {
                "project_member": bool(record),
                "core_eligible": source_is_core,
                "same_sub_hypothesis": same_branch,
                "source_sub_hypothesis_id": source_branch,
                "boundary_extension": boundary_record,
                "foundational_mechanism_bridge": foundation,
                "domain_review_verdict": domain_verdict,
                "eligible_for_direct_source_role": identity_valid,
                "fully_project_outside": fully_project_outside,
            },
        })
    return results


def pre_rank_gap_source_role_route(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Run the bounded original-fragment role gate before any Top-N cutoff.

    The audit is intentionally small: it classifies only the source units that
    created this candidate, not every sentence of every paper.  Full theory +
    experiment bundle construction still occurs later for candidates that
    survive this discovery gate.
    """
    item = dict(gap)
    item["source_state"] = "SOURCE_CANDIDATE"
    pool = str(item.get("gap_candidate_pool") or default_gap_candidate_pool(str(item.get("gap_type") or "")))
    if pool in {SECONDARY_RESEARCH_OPPORTUNITY_POOL, EVIDENCE_EXTRACTION_SHORTAGE_POOL}:
        item["gap_candidate_pool"] = pool
        item["source_alignment_verdict"] = {
            "version": "source_alignment_verdict_v1",
            "verdict": "RATIONALE_ALIGNED" if pool == SECONDARY_RESEARCH_OPPORTUNITY_POOL else "UNVERIFIABLE_SOURCE",
            "passes_for_direct": False,
            "source_roles": [],
            "fully_project_outside": False,
            "reason": (
                "The generator declared this item to be a structural, coverage, migration, or abductive secondary opportunity."
                if pool == SECONDARY_RESEARCH_OPPORTUNITY_POOL
                else "The generator declared an evidence-extraction shortage."
            ),
        }
        item["pre_rank_source_role_audit"] = {
            "status": (
                "DECLARED_SECONDARY_GENERATOR"
                if pool == SECONDARY_RESEARCH_OPPORTUNITY_POOL
                else "DECLARED_EXTRACTION_SHORTAGE"
            ),
            "source_roles": [],
            "socrates_targeted_retrieval_allowed": False,
        }
        return item
    source_units = [unit for unit in item.get("source_evidence_units", []) if isinstance(unit, dict)]
    contextual_source_units = [
        unit for unit in (item.get("contextual_source_evidence_units") or [])
        if isinstance(unit, dict)
    ]
    epistemic = item.get("gap_epistemic_audit") if isinstance(item.get("gap_epistemic_audit"), dict) else {}
    if not source_units:
        source_hints = []
        for payload in (
            item.get("gap_signal"), item.get("mechanism_issue_signal"),
            item.get("causal_gap"), item.get("reasoning_signal"),
            item.get("source_candidate_provenance"),
        ):
            if not isinstance(payload, dict):
                continue
            source_hints.extend(
                str(payload.get(key) or "").strip()
                for key in ("paper_id", "source_unit_id", "excerpt_hash", "source_field")
                if str(payload.get(key) or "").strip()
            )
            location = payload.get("source_location")
            if isinstance(location, dict) and location:
                source_hints.append("source_location")
            for source in payload.get("sources", []) if isinstance(payload.get("sources"), list) else []:
                if not isinstance(source, dict):
                    continue
                source_hints.extend(
                    str(source.get(key) or "").strip()
                    for key in ("paper_id", "source_unit_id", "excerpt_hash", "source_field")
                    if str(source.get(key) or "").strip()
                )
        legacy_unverifiable = not bool(source_hints)
        item["pre_rank_source_role_audit"] = {
            "status": "LEGACY_SOURCE_UNVERIFIABLE" if legacy_unverifiable else "SOURCE_PROVENANCE_INCOMPLETE",
            "source_roles": [],
            "socrates_targeted_retrieval_allowed": False,
        }
        item["source_alignment_verdict"] = {
            "version": "source_alignment_verdict_v1",
            "verdict": "UNVERIFIABLE_SOURCE",
            "passes_for_direct": False,
            "source_roles": [],
            "fully_project_outside": False,
            "reason": "No paper-qualified source evidence unit is attached to the candidate seed.",
        }
        item["legacy_source_status"] = "LEGACY_SOURCE_UNVERIFIABLE" if legacy_unverifiable else ""
        item["gap_candidate_pool"] = (
            SECONDARY_RESEARCH_OPPORTUNITY_POOL
            if legacy_unverifiable
            else EVIDENCE_EXTRACTION_SHORTAGE_POOL
        )
        return item
    core_records = mechanism_core_records(project)
    core_record_ids = {
        str(record.get("paper_id") or record.get("doi") or "")
        for record in core_records
        if isinstance(record, dict)
    }
    all_records = [
        record for record in (
            # Evidence is a compact compatibility projection.  Put canonical
            # PaperGraph records last so the dictionary below cannot replace
            # their alignment/source fields with a projection.
            list(project.get("evidence") or []) + list(project.get("papergraph") or [])
        )
        if isinstance(record, dict)
    ]
    records = {
        str(record.get("paper_id") or record.get("doi") or ""): record
        for record in all_records
    }
    branch = normalized_subhypothesis_id(item.get("sub_hypothesis_id"))
    if not branch:
        for source in source_units:
            record = records.get(str(source.get("paper_id") or ""), {})
            branch = next(iter(_record_subhypothesis_ids_for_aggregation(record)), "")
            if branch:
                break
    if branch:
        item["sub_hypothesis_id"] = branch
    contracts = project.get("subhypothesis_alignment_contracts") if isinstance(project.get("subhypothesis_alignment_contracts"), dict) else {}
    contract = contracts.get(branch) if branch else {}
    if not isinstance(contract, dict):
        contract = {}
    if not contract and branch:
        subhypothesis = next(
            (
                candidate for candidate in (project.get("sub_hypotheses") or [])
                if isinstance(candidate, dict) and normalized_subhypothesis_id(candidate.get("id")) == branch
            ),
            {},
        )
        if subhypothesis:
            try:
                from ._research_alignment import build_project_alignment_card, build_subhypothesis_alignment_contract
            except ImportError:
                from _research_alignment import build_project_alignment_card, build_subhypothesis_alignment_contract
            contract = build_subhypothesis_alignment_contract(
                project,
                subhypothesis,
                build_project_alignment_card(project),
            )
    role_results: list[dict[str, Any]] = []
    if contract:
        try:
            from ._evidence_fragment_alignment import assess_evidence_fragment_alignment
        except ImportError:
            from _evidence_fragment_alignment import assess_evidence_fragment_alignment
        for source in source_units:
            excerpt = str(source.get("excerpt") or "").strip()
            record = records.get(str(source.get("paper_id") or ""), {})
            if not excerpt:
                continue
            synthetic = {
                "paper_id": str(source.get("paper_id") or ""),
                "full_text_excerpt": excerpt,
                "paper_genre": dict(record.get("paper_genre") or {}) if isinstance(record.get("paper_genre"), dict) else {},
                "publication_type": str(record.get("publication_type") or ""),
            }
            alignments = assess_evidence_fragment_alignment(synthetic, contract, window_size=1, use_llm=False)
            best = max(
                alignments,
                key=lambda alignment: (
                    {"direct": 3, "partial": 2, "rationale_only": 1, "out_of_scope": 0}.get(str(alignment.get("source_role") or ""), -1),
                    float(alignment.get("confidence") or 0.0),
                ),
                default={},
            )
            source_paper_id = str(source.get("paper_id") or "")
            source_is_core = source_paper_id in core_record_ids or not bool(project.get("subhypothesis_alignment_contracts"))
            source_branch = next(iter(_record_subhypothesis_ids_for_aggregation(record)), "")
            same_branch = bool(branch and source_branch and branch == source_branch)
            boundary_record = str(record.get("retrieval_phase") or "") == "boundary_extension"
            foundation = gap_record_is_foundational_bridge(record)
            domain_verdict = str(record.get("domain_review_verdict") or "keep").lower()
            fully_project_outside = bool(not source_is_core or domain_verdict == "reject")
            source_identity_valid = bool(
                source_is_core and same_branch and not boundary_record and not foundation and domain_verdict not in {"review", "reject"}
            )
            if foundation:
                source_role = "rationale_only"
            elif not source_identity_valid:
                source_role = "out_of_scope"
            else:
                source_role = str(best.get("source_role") or "unresolved")
            raw_genre = record.get("paper_genre")
            paper_genre = str(
                raw_genre.get("genre")
                if isinstance(raw_genre, dict)
                else raw_genre
                or record.get("publication_type")
                or ""
            )
            role_results.append({
                "paper_id": source_paper_id,
                "source_unit_id": str(source.get("source_unit_id") or ""),
                "excerpt_hash": str(source.get("excerpt_hash") or ""),
                "binding_status": str(source.get("binding_status") or ""),
                "excerpt": str(source.get("excerpt") or "")[:1200],
                "source_field": str(source.get("source_field") or ""),
                "paper_genre": paper_genre,
                "source_role": source_role,
                "semantic_verdict": (
                    "FOUNDATIONAL_BRIDGE_RATIONALE_ONLY"
                    if foundation
                    else str(best.get("semantic_verdict") or "UNRESOLVED")
                    if source_identity_valid
                    else "SOURCE_IDENTITY_NOT_ELIGIBLE"
                ),
                "causal_fields_supported": list(best.get("causal_fields_supported") or []),
                "object_alignment": dict(best.get("object_alignment") or {}) if isinstance(best.get("object_alignment"), dict) else {},
                "process_alignment": dict(best.get("process_alignment") or {}) if isinstance(best.get("process_alignment"), dict) else {},
                "outcome_alignment": dict(best.get("outcome_alignment") or {}) if isinstance(best.get("outcome_alignment"), dict) else {},
                "source_identity": {
                    "project_member": bool(record),
                    "core_eligible": source_is_core,
                    "same_sub_hypothesis": same_branch,
                    "source_sub_hypothesis_id": source_branch,
                    "boundary_extension": boundary_record,
                    "foundational_mechanism_bridge": foundation,
                    "domain_review_verdict": domain_verdict,
                    "eligible_for_direct_source_role": source_identity_valid,
                    "fully_project_outside": fully_project_outside,
                },
                "rejection_reasons": (
                    list(best.get("rejection_reasons") or [])
                    if source_identity_valid
                    else (
                        ["foundational_mechanism_bridge_is_rationale_only"]
                        if foundation
                        else ["source_paper_not_core_eligible_for_current_project_and_subhypothesis"]
                    )
                ),
            })
    contextual_role_results = _assess_contextual_source_units(
        project,
        contextual_source_units,
        contract,
        branch,
        records,
        core_record_ids,
    )
    roles = [str(result.get("source_role") or "unresolved") for result in role_results]
    verified = bool(source_units) and all(source.get("binding_status") == "SOURCE_UNIT_VERIFIED" for source in source_units)
    if not contract:
        status = "SOURCE_ROLE_CONTRACT_UNAVAILABLE"
        routed_pool = COMPOSITE_GAP_AUDIT_POOL
    elif not verified:
        status = "SOURCE_UNIT_BINDING_UNRESOLVED"
        routed_pool = EVIDENCE_EXTRACTION_SHORTAGE_POOL
    elif "direct" in roles and epistemic.get("passes"):
        status = "DIRECT_SOURCE_ROLE_CANDIDATE"
        routed_pool = PRIMARY_MECHANISM_CANDIDATE_POOL
    elif roles and all(role in {"rationale_only", "out_of_scope"} for role in roles):
        status = "ORIGINAL_SOURCE_ROLE_INVALID"
        routed_pool = SECONDARY_RESEARCH_OPPORTUNITY_POOL
    else:
        status = "PARTIAL_SOURCE_ROLE_REQUIRES_COMPOSITE_AUDIT"
        routed_pool = COMPOSITE_GAP_AUDIT_POOL
    item["pre_rank_source_role_audit"] = {
        "status": status,
        "sub_hypothesis_id": branch,
        "source_roles": [
            {
                "paper_id": str(result.get("paper_id") or ""),
                "source_unit_id": str(result.get("source_unit_id") or ""),
                "source_role": str(result.get("source_role") or "unresolved"),
                "semantic_verdict": str(result.get("semantic_verdict") or "UNRESOLVED"),
            }
            for result in role_results
        ],
        "contextual_source_roles": [
            {
                "paper_id": str(result.get("paper_id") or ""),
                "source_unit_id": str(result.get("source_unit_id") or ""),
                "source_role": str(result.get("source_role") or "unresolved"),
                "semantic_verdict": str(result.get("semantic_verdict") or "UNRESOLVED"),
                "causal_fields_supported": list(result.get("causal_fields_supported") or []),
            }
            for result in contextual_role_results
        ],
        "epistemic_verdict": str(epistemic.get("verdict") or "UNRESOLVED"),
        "socrates_targeted_retrieval_allowed": bool(
            status in {"DIRECT_SOURCE_ROLE_CANDIDATE", "PARTIAL_SOURCE_ROLE_REQUIRES_COMPOSITE_AUDIT"}
        ),
    }
    item["source_alignment_verdict"] = build_source_alignment_verdict(
        item,
        role_results,
        contract_available=bool(contract),
        verified=verified,
        contextual_role_results=contextual_role_results,
    )
    item["gap_candidate_pool"] = routed_pool
    if branch:
        item["sub_hypothesis_id"] = branch
    return item


def _tanxi_semantic_candidate_identity_and_fingerprint(
    candidate: dict[str, Any],
) -> tuple[str, str]:
    """Return a stable V2 audit checkpoint key for one detector candidate."""
    payload = candidate if isinstance(candidate, dict) else {}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    fingerprint = "sha256:" + sha256(encoded).hexdigest()
    identity = str(payload.get("candidate_identity") or "").strip()
    return identity or f"candidate:{fingerprint[7:31]}", fingerprint


_TANXI_SEMANTIC_AUDIT_CHECKPOINT_FIELDS = (
    "gap_assessment",
    "semantic_audit",
    "semantic_assessment",
    "gap_type",
    "gap_subtype",
    "signal_type",
    "candidate_stage",
    "route",
    "qualification",
    "evidence_refs",
    "source_span_refs",
    "assessment_version",
)

_TANXI_SOURCE_BODY_FIELDS = frozenset({
    "excerpt",
    "quote",
    "source_quote",
    "supporting_phrase",
    "document",
    "full_text",
    "fulltext",
})


def _tanxi_reference_only_value(value: Any) -> Any:
    """Drop source text while retaining IDs, hashes, and source locations."""
    if isinstance(value, dict):
        return {
            str(key): _tanxi_reference_only_value(item)
            for key, item in value.items()
            if str(key) not in _TANXI_SOURCE_BODY_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_tanxi_reference_only_value(item) for item in value]
    return copy.deepcopy(value)


def _tanxi_semantic_audit_reference_projection(value: Any) -> dict[str, Any]:
    """Project semantic-audit state without repeating source phrases."""
    audit = value if isinstance(value, dict) else {}
    allowed_component_fields = {
        "semantic_verdict",
        "confidence",
        "failure_codes",
        "supporting_source_unit_ids",
        "field_support",
        "audit_output_status",
        "audit_failure_class",
    }
    projected: dict[str, Any] = {
        key: _tanxi_reference_only_value(audit[key])
        for key in (
            "schema_version",
            "candidate_identity",
            "assessment_version",
            "graph_snapshot_ref",
            "retrieval_rebind_fingerprint",
            "audit_output_status",
            "audit_failure_class",
        )
        if key in audit
    }
    for role in ("deterministic", "positive", "red_team"):
        component = audit.get(role) if isinstance(audit.get(role), dict) else {}
        projected[role] = {
            key: _tanxi_reference_only_value(component[key])
            for key in allowed_component_fields
            if key in component
        }
    projected["checks"] = {
        str(key): bool(item)
        for key, item in (audit.get("checks") or {}).items()
    }
    projected["payload_policy"] = "source_ids_hashes_offsets_and_verdicts_only"
    return projected


def _tanxi_semantic_assessment_reference_projection(value: Any) -> dict[str, Any]:
    """Keep the resumable semantic summary, not LLM source-text echoes."""
    assessment = value if isinstance(value, dict) else {}
    projected = {
        key: _tanxi_reference_only_value(assessment[key])
        for key in (
            "schema_version",
            "audit_request_schema",
            "verdict",
            "confidence",
            "failure_codes",
            "audit_output_status",
            "audit_failure_class",
        )
        if key in assessment
    }
    for key in ("positive_field_support", "red_team_field_support"):
        if key in assessment:
            projected[key] = _tanxi_reference_only_value(assessment[key])
    projected["payload_policy"] = "source_ids_hashes_offsets_and_verdicts_only"
    return projected


def _tanxi_semantic_audit_checkpoint_projection(
    audited_candidate: dict[str, Any],
) -> dict[str, Any]:
    """Persist only one candidate's semantic decision, never its source body."""
    candidate = audited_candidate if isinstance(audited_candidate, dict) else {}
    projection: dict[str, Any] = {}
    for key in _TANXI_SEMANTIC_AUDIT_CHECKPOINT_FIELDS:
        if key not in candidate:
            continue
        if key == "semantic_audit":
            projection[key] = _tanxi_semantic_audit_reference_projection(candidate[key])
        elif key == "semantic_assessment":
            projection[key] = _tanxi_semantic_assessment_reference_projection(candidate[key])
        else:
            projection[key] = _tanxi_reference_only_value(candidate[key])
    projection["payload_policy"] = "source_ids_hashes_offsets_and_verdicts_only"
    return projection


def _hydrate_tanxi_semantic_audit_checkpoint(
    candidate: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any] | None:
    """Merge a fingerprint-matched semantic decision into a fresh detector lead."""
    fresh = copy.deepcopy(candidate) if isinstance(candidate, dict) else {}
    saved = projection if isinstance(projection, dict) else {}
    assessment = saved.get("gap_assessment")
    semantic_audit = saved.get("semantic_audit")
    if (
        not isinstance(assessment, dict)
        or assessment.get("schema_version") != "gap_assessment_v2"
        or not isinstance(semantic_audit, dict)
    ):
        return None
    for key in _TANXI_SEMANTIC_AUDIT_CHECKPOINT_FIELDS:
        if key in saved:
            fresh[key] = copy.deepcopy(saved[key])
    # The fresh detector lead remains authoritative for source units, type
    # payload, current contract, and question scope.  The checkpoint holds
    # only the previous semantic adjudication of that unchanged lead.
    return fresh


def _hydrate_tanxi_candidate_source_units(
    candidate: dict[str, Any],
    runtime_source_spans_by_id: dict[str, Any],
) -> dict[str, Any]:
    """Attach verified runtime excerpts to a reference-only detector lead.

    Detector artifacts deliberately omit source text.  Before replaying such
    a lead through semantic audit, resolve only its listed span IDs from this
    invocation's already-narrow evidence view and require paper/version/hash
    agreement.  Missing or mismatched records stay text-free and therefore
    fail the audit as an explicit provenance shortage.
    """
    output = copy.deepcopy(candidate) if isinstance(candidate, dict) else {}
    source_units = [
        item for item in output.get("source_evidence_units", [])
        if isinstance(item, dict)
    ]
    hydrated_units: list[dict[str, Any]] = []
    for unit in source_units:
        hydrated = dict(unit)
        span_id = str(
            hydrated.get("source_span_id") or hydrated.get("source_unit_id") or ""
        )
        runtime = runtime_source_spans_by_id.get(span_id)
        if not isinstance(runtime, dict):
            hydrated_units.append(hydrated)
            continue
        expected_paper_id = str(hydrated.get("paper_id") or "")
        expected_version = str(hydrated.get("document_version_hash") or "")
        expected_quote_hash = str(
            hydrated.get("quote_hash") or hydrated.get("excerpt_hash") or ""
        )
        runtime_quote_hash = str(
            runtime.get("quote_hash") or runtime.get("excerpt_hash") or ""
        )
        if (
            str(runtime.get("paper_id") or "") != expected_paper_id
            or str(runtime.get("document_version_hash") or "") != expected_version
            or (expected_quote_hash and runtime_quote_hash != expected_quote_hash)
        ):
            hydrated_units.append(hydrated)
            continue
        excerpt = str(runtime.get("quote") or runtime.get("excerpt") or "")
        if excerpt:
            hydrated["excerpt"] = excerpt
        hydrated_units.append(hydrated)
    output["source_evidence_units"] = hydrated_units
    return output


def _gap_resolution_work_item_id(work_item: dict[str, Any]) -> str:
    """Return the stable queue identity for one immutable V3 work item."""

    payload = {
        key: value
        for key, value in (work_item if isinstance(work_item, dict) else {}).items()
        if key != "work_item_id"
    }
    return "gap_resolution_" + sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:24]


def _gap_resolution_target_slots_v3(
    candidate: dict[str, Any],
    branch_states: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any] | None]:
    """Resolve a targeted candidate to declared slots without broad fallback.

    Explicit plan slots are authoritative.  If they are not present, only the
    matching branch's declared missing direct slots may become a target.  An
    otherwise valid candidate with no such mapping remains pending instead of
    being converted into an all-slots or topic search.
    """

    source = candidate if isinstance(candidate, dict) else {}
    plan = source.get("retrieval_plan") if isinstance(source.get("retrieval_plan"), dict) else {}
    contract = (
        source.get("research_question_contract")
        if isinstance(source.get("research_question_contract"), dict)
        else {}
    )
    declared_slots = {
        str(item).strip()
        for item in ((contract.get("evidence_contract") or {}).get("required_slots") or [])
        if str(item).strip()
    }
    candidate_identity = str(source.get("candidate_identity") or "")
    if contract.get("schema_version") != "research_question_contract_v3" or not declared_slots:
        return [], {
            "schema_version": "retrieval_diagnostic_v3",
            "stage": "CONTRACT_VALIDATION",
            "outcome": "BLOCKED",
            "reason_code": "GAP_RESOLUTION_CURRENT_V3_CONTRACT_REQUIRED",
            "candidate_identity": candidate_identity,
            "evidence_ids": [],
            "retry_recommended": False,
        }

    explicit_slots = sorted({
        str(item).strip()
        for item in plan.get("target_slot_ids", [])
        if str(item).strip()
    })
    if explicit_slots:
        invalid_slots = sorted(set(explicit_slots) - declared_slots)
        if invalid_slots:
            return [], {
                "schema_version": "retrieval_diagnostic_v3",
                "stage": "CONTRACT_VALIDATION",
                "outcome": "BLOCKED",
                "reason_code": "GAP_RESOLUTION_TARGET_SLOT_NOT_DECLARED_BY_CONTRACT",
                "candidate_identity": candidate_identity,
                "target_slot_ids": explicit_slots,
                "invalid_slot_ids": invalid_slots,
                "evidence_ids": [],
                "retry_recommended": False,
            }
        return explicit_slots, None

    sub_hypothesis_id = str(contract.get("sub_hypothesis_id") or "").strip()
    matching_branches = [
        branch
        for branch in branch_states
        if isinstance(branch, dict)
        and str(branch.get("sub_hypothesis_id") or "").strip() == sub_hypothesis_id
    ]
    missing_slots = sorted({
        str(slot).strip()
        for branch in matching_branches
        for slot in branch.get("missing_direct_slot_ids", [])
        if str(slot).strip()
    })
    invalid_slots = sorted(set(missing_slots) - declared_slots)
    if invalid_slots:
        return [], {
            "schema_version": "retrieval_diagnostic_v3",
            "stage": "CONTRACT_VALIDATION",
            "outcome": "FAILED",
            "reason_code": "GAP_RESOLUTION_BRANCH_SLOT_OUTSIDE_CURRENT_CONTRACT",
            "candidate_identity": candidate_identity,
            "invalid_slot_ids": invalid_slots,
            "evidence_ids": [],
            "retry_recommended": False,
        }
    if missing_slots:
        return missing_slots, None
    return [], {
        "schema_version": "retrieval_diagnostic_v3",
        "stage": "CONTRACT_VALIDATION",
        "outcome": "BLOCKED",
        "reason_code": "GAP_RESOLUTION_SLOT_BINDING_REQUIRED",
        "candidate_identity": candidate_identity,
        "research_question_contract_id": str(contract.get("contract_id") or ""),
        "evidence_ids": [],
        "retry_recommended": False,
    }


def build_gap_resolution_work_items_v3(
    project: dict[str, Any],
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    branch_states: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create independent V3 GAP_RESOLUTION work items for routed candidates.

    The function is deliberately a queue builder, not a retriever.  It gives
    every targeted candidate an exact work item or a structured slot-binding
    diagnostic.  It never reuses another candidate's result and never turns a
    missing mapping into a broad SH search.
    """

    graph_ref = graph_snapshot_ref(snapshot if isinstance(snapshot, dict) else {})
    graph_snapshot_id = str(graph_ref.get("snapshot_id") or "").strip()
    if not graph_snapshot_id:
        updated_candidates: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for raw_candidate in candidates:
            candidate = dict(raw_candidate) if isinstance(raw_candidate, dict) else {}
            if assessment_of(candidate).get("route") != GapRoute.TARGETED_RETRIEVAL.value:
                updated_candidates.append(candidate)
                continue
            candidate_identity = str(candidate.get("candidate_identity") or "")
            diagnostic = {
                "schema_version": "retrieval_diagnostic_v3",
                "stage": "GRAPH_BINDING",
                "outcome": "BLOCKED",
                "reason_code": "GAP_RESOLUTION_CURRENT_GRAPH_SNAPSHOT_REQUIRED",
                "candidate_identity": candidate_identity,
                "evidence_ids": [],
                "retry_recommended": True,
            }
            candidate["gap_resolution_retrieval"] = {
                "schema_version": "gap_resolution_retrieval_state_v3",
                "status": "PENDING_GRAPH_SNAPSHOT",
                "stage": "GRAPH_BINDING",
                "reason_code": diagnostic["reason_code"],
                "candidate_identity": candidate_identity,
                "target_slot_ids": [],
                "missing_obligation_slot_ids": [],
                "next_stage": "REFRESH_RESEARCH_EVIDENCE_GRAPH_V3_SNAPSHOT",
                "diagnostic": diagnostic,
            }
            diagnostics.append(diagnostic)
            updated_candidates.append(candidate)
        return updated_candidates, [], diagnostics
    updated_candidates: list[dict[str, Any]] = []
    work_items: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate) if isinstance(raw_candidate, dict) else {}
        if assessment_of(candidate).get("route") != GapRoute.TARGETED_RETRIEVAL.value:
            updated_candidates.append(candidate)
            continue
        plan = candidate.get("retrieval_plan") if isinstance(candidate.get("retrieval_plan"), dict) else {}
        candidate_identity = str(candidate.get("candidate_identity") or "")
        if plan.get("schema_version") != "gap_search_plan_v3":
            diagnostic = {
                "schema_version": "retrieval_diagnostic_v3",
                "stage": "CONTRACT_VALIDATION",
                "outcome": "FAILED",
                "reason_code": "GAP_RESOLUTION_SEARCH_PLAN_V3_REQUIRED",
                "candidate_identity": candidate_identity,
                "evidence_ids": [],
                "retry_recommended": False,
            }
            candidate["gap_resolution_retrieval"] = {
                "schema_version": "gap_resolution_retrieval_state_v3",
                "status": "PENDING_SLOT_BINDING",
                "stage": "CONTRACT_VALIDATION",
                "reason_code": diagnostic["reason_code"],
                "candidate_identity": candidate_identity,
                "target_slot_ids": [],
                "missing_obligation_slot_ids": [],
                "next_stage": "REBUILD_GAP_SEARCH_PLAN_V3",
                "diagnostic": diagnostic,
            }
            diagnostics.append(diagnostic)
            updated_candidates.append(candidate)
            continue

        target_slots, diagnostic = _gap_resolution_target_slots_v3(candidate, branch_states)
        if diagnostic is not None:
            candidate["gap_resolution_retrieval"] = {
                "schema_version": "gap_resolution_retrieval_state_v3",
                "status": "PENDING_SLOT_BINDING",
                "stage": str(diagnostic.get("stage") or "CONTRACT_VALIDATION"),
                "reason_code": str(diagnostic.get("reason_code") or "GAP_RESOLUTION_SLOT_BINDING_REQUIRED"),
                "candidate_identity": candidate_identity,
                "target_slot_ids": [],
                "missing_obligation_slot_ids": [],
                "next_stage": "BIND_DECLARED_TARGET_SLOT",
                "diagnostic": diagnostic,
            }
            diagnostics.append(diagnostic)
            updated_candidates.append(candidate)
            continue

        candidate["retrieval_plan"] = {
            **plan,
            "target_slot_ids": target_slots,
        }
        try:
            work_item = build_gap_resolution_work_item_v3(
                candidate,
                target_slot_ids=target_slots,
                graph_snapshot_id=graph_snapshot_id,
            )
        except ValueError as exc:
            diagnostic = {
                "schema_version": "retrieval_diagnostic_v3",
                "stage": "CONTRACT_VALIDATION",
                "outcome": "FAILED",
                "reason_code": "GAP_RESOLUTION_WORK_ITEM_REJECTED",
                "candidate_identity": candidate_identity,
                "detail": str(exc),
                "evidence_ids": [],
                "retry_recommended": False,
            }
            candidate["gap_resolution_retrieval"] = {
                "schema_version": "gap_resolution_retrieval_state_v3",
                "status": "WORKFLOW_ERROR",
                "stage": "CONTRACT_VALIDATION",
                "reason_code": diagnostic["reason_code"],
                "candidate_identity": candidate_identity,
                "target_slot_ids": target_slots,
                "missing_obligation_slot_ids": target_slots,
                "next_stage": "REPAIR_V3_WORK_ITEM_BINDING",
                "diagnostic": diagnostic,
            }
            diagnostics.append(diagnostic)
            updated_candidates.append(candidate)
            continue
        work_item_id = _gap_resolution_work_item_id(work_item)
        work_item = {**work_item, "work_item_id": work_item_id}
        retrieval_state = {
            "schema_version": "gap_resolution_retrieval_state_v3",
            "status": "PENDING",
            "stage": "QUERY_COMPILATION",
            "reason_code": "GAP_RESOLUTION_WORK_ITEM_SCHEDULED",
            "candidate_identity": candidate_identity,
            "gap_candidate_fingerprint": str(work_item.get("gap_candidate_fingerprint") or ""),
            "gap_search_plan_fingerprint": str(work_item.get("plan_fingerprint") or ""),
            "research_question_contract_id": str(work_item.get("research_question_contract_id") or ""),
            "research_question_contract_revision": str(work_item.get("research_question_contract_revision") or ""),
            "graph_snapshot_id": graph_snapshot_id,
            "work_item_id": work_item_id,
            "target_slot_ids": target_slots,
            "missing_obligation_slot_ids": target_slots,
            "next_stage": "PROVIDER_EXECUTION",
        }
        candidate["retrieval_work_item_v3"] = work_item
        candidate["gap_resolution_retrieval"] = retrieval_state
        updated_candidates.append(candidate)
        work_items.append({
            **work_item,
            "execution_state": retrieval_state,
        })
    return updated_candidates, work_items, diagnostics


def _select_tanxi_display_candidates_v3(
    candidates: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """Apply the report budget after type-and-contract semantic auditing."""

    budget = max(0, int(max_candidates))
    if not budget:
        return []
    route_order = {
        GapRoute.PRIMARY_CANDIDATE.value: 0,
        GapRoute.TARGETED_RETRIEVAL.value: 1,
        GapRoute.SECONDARY_RESEARCH.value: 2,
        GapRoute.DIAGNOSTIC.value: 3,
        GapRoute.REJECT.value: 4,
    }
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        assessment = assessment_of(candidate)
        context_ref = (
            candidate.get("detection_context_ref")
            if isinstance(candidate.get("detection_context_ref"), dict)
            else {}
        )
        gap_type = str(assessment.get("gap_type") or "")
        contract_id = str(
            context_ref.get("research_question_contract_id")
            or (candidate.get("research_question_contract") or {}).get("contract_id")
            or ""
        )
        if not gap_type or not contract_id:
            raise ValueError("TANXI_DISPLAY_SELECTION_REQUIRES_TYPE_AND_CONTRACT")
        buckets[(gap_type, contract_id)].append(candidate)
    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: (
                route_order.get(str(assessment_of(item).get("route") or ""), 9),
                str(item.get("candidate_identity") or ""),
            )
        )
    ordered_buckets = sorted(
        buckets,
        key=lambda key: (
            route_order.get(
                str(assessment_of(buckets[key][0]).get("route") or ""),
                9,
            ),
            key[0],
            key[1],
        ),
    )
    selected: list[dict[str, Any]] = []
    position = 0
    while len(selected) < budget:
        emitted = False
        for key in ordered_buckets:
            bucket = buckets[key]
            if position >= len(bucket):
                continue
            selected.append(bucket[position])
            emitted = True
            if len(selected) >= budget:
                break
        if not emitted:
            break
        position += 1
    return selected


def tanxi_gap_exploration_report(
    project: dict[str, Any],
    *,
    max_gaps: int = 10,
    semantic_auditor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    red_team_auditor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    graph_snapshot: dict[str, Any] | None = None,
    detector_checkpoint: dict[str, Any] | None = None,
    on_detector_complete: Callable[[str, dict[str, Any]], None] | None = None,
    load_detector_result: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    on_detector_started: Callable[[dict[str, Any]], None] | None = None,
    semantic_audit_checkpoint: dict[str, Any] | None = None,
    on_semantic_audit_started: Callable[[dict[str, Any]], None] | None = None,
    on_semantic_candidate_started: Callable[[str, dict[str, Any]], None] | None = None,
    on_semantic_candidate_complete: Callable[[str, dict[str, Any]], None] | None = None,
    targeted_retrieval_executor: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    max_targeted_retrieval_cycles: int = 1,
    detector_max_workers: int = 12,
) -> dict[str, Any]:
    """Discover, type, audit, and route source-bound scientific-gap candidates.

    Discovery is deliberately not a scientific-gap verdict.  Every candidate
    is classified into a type-specific contract, audited against its exact
    source spans, and given either a diagnostic route or a type-directed
    retrieval plan.  Primary status can only be assigned later by
    :func:`qualify_gap_candidate` with a retrieval assessment artifact.
    """
    if not _project_uses_research_question_evidence_v3(project):
        return {
            "schema_version": "tanxi_gap_report_v3",
            "project_id": str(project.get("project_id") or ""),
            "ranked_gaps": [],
            "research_packages": [],
            "primary_research_candidates": [],
            "primary_mechanism_candidates": [],
            "targeted_retrieval_candidates": [],
            "gap_resolution_work_items_v3": [],
            "secondary_research_candidates": [],
            "evidence_extraction_shortages": [],
            "branch_gap_states": [],
            "candidate_ledger": {},
            "tanxi_candidate_funnel": {
                "schema_version": "tanxi_gap_funnel_v3",
                "candidate_count": 0,
                "reason": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            },
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "reason": (
                "TanXi V3 accepts only explicitly declared ResearchQuestionContractV3 SHs; "
                "legacy causal chains and alignment artefacts are not adapted."
            ),
        }
    if int(max_targeted_retrieval_cycles) != 1:
        raise ValueError("TanXi V3 permits exactly one bounded targeted retrieval cycle per invocation")
    snapshot = graph_snapshot if isinstance(graph_snapshot, dict) else None
    if not isinstance(snapshot, dict) or str(snapshot.get("schema_version") or "") != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        raise ValueError(
            "TANXI_V3_GRAPH_SNAPSHOT_REQUIRED: TanXi must receive the current detached "
            "research_evidence_graph_v4; full-project graph reconstruction is disabled."
        )
    project["_tanxi_graph_snapshot"] = snapshot
    snapshot_ref = graph_snapshot_ref(snapshot)
    workflow_integrity = (
        snapshot.get("workflow_integrity")
        if isinstance(snapshot.get("workflow_integrity"), dict)
        else {}
    )
    if str(workflow_integrity.get("status") or "") == "INTEGRITY_ERROR":
        integrity_errors = [
            item
            for item in workflow_integrity.get("artifact_integrity_errors_v4", [])
            if isinstance(item, dict)
        ]
        diagnostics = [
            {
                "stage": "evidence_artifact_integrity",
                "reason": "REFERENCE_FIRST_ASSERTION_PROVENANCE_INCOMPLETE",
                "artifact_integrity_errors_v4": integrity_errors,
                "scientific_interpretation_allowed": False,
            }
        ]
        return {
            "agent": "tanxi",
            "schema_version": "tanxi_gap_report_v3",
            "status": "NEEDS_EVIDENCE_ARTIFACT_INTEGRITY_REPAIR",
            "thought": (
                "TanXi stopped before source-bound scientific-gap detection because "
                "the immutable assertion provenance ledger is incomplete."
            ),
            "ranked_gaps": [],
            "primary_research_candidates": [],
            "primary_mechanism_candidates": [],
            "research_packages": [],
            "research_packages_by_kind": {},
            "research_package_candidate_dispatch": {},
            "targeted_retrieval_candidates": [],
            "gap_resolution_work_items_v3": [],
            "secondary_research_candidates": [],
            "diagnostic_candidates": diagnostics,
            "subhypothesis_gap_handoffs": [],
            "verification_tasks": [],
            "gap_candidate_ledger": {},
            "tanxi_candidate_funnel": {
                "schema_version": "tanxi_gap_funnel_v3",
                "artifact_integrity_error_count": len(integrity_errors),
                "candidate_count": 0,
                "scientific_detection_skipped": True,
            },
            "evidence_graph": {},
            "research_evidence_graph_ref": snapshot_ref,
            "research_evidence_graph_quality": dict(snapshot.get("quality_audit") or {}),
            "research_evidence_graph_workflow_integrity": workflow_integrity,
            "branch_gap_states": [],
            "diagnostics": diagnostics,
            "evidence_extraction_shortages": [],
            "rejected_scientific_candidates": diagnostics,
            "candidate_pools": {
                "by_gap_type": {},
                "by_semantic_status": {},
                "by_route": {},
                "research_packages_by_kind": {},
                "evidence_extraction_shortages": [],
            },
            "candidate_filter": {
                "source_span_and_assertion_lineage_required": True,
                "scientific_detection_skipped_for_artifact_integrity": True,
            },
        }
    try:
        from ._gap_evidence_graph import run_source_bound_gap_detection
    except ImportError:
        from _gap_evidence_graph import run_source_bound_gap_detection
    normalized_detector_checkpoint = (
        detector_checkpoint if isinstance(detector_checkpoint, dict) else {}
    )
    if callable(on_detector_started):
        on_detector_started(
            {
                "completed_detector_count": len(
                    normalized_detector_checkpoint.get("completed_detector_ids") or []
                ),
                "checkpointed_detector_count": len(
                    normalized_detector_checkpoint.get("detector_result_refs") or {}
                ),
            }
        )
    graph_report = run_source_bound_gap_detection(
        project,
        audit_candidate_budget_per_type_contract=6,
        audit_frontier_resume_state_v3=(
            normalized_detector_checkpoint.get("audit_frontier_resume_state_v3")
            if isinstance(
                normalized_detector_checkpoint.get("audit_frontier_resume_state_v3"),
                dict,
            )
            else None
        ),
        detector_checkpoint=normalized_detector_checkpoint,
        on_detector_complete=on_detector_complete,
        load_detector_result=load_detector_result,
        detector_max_workers=max(1, min(12, int(detector_max_workers or 1))),
    )
    runtime_source_spans_by_id = (
        project.get("_tanxi_runtime_source_spans_by_id")
        if isinstance(project.get("_tanxi_runtime_source_spans_by_id"), dict)
        else {}
    )
    discovered = [
        _hydrate_tanxi_candidate_source_units(
            item,
            runtime_source_spans_by_id,
        )
        for item in graph_report.get("candidates", [])
        if isinstance(item, dict)
    ]
    audit_continuation_frontier = [
        item
        for item in graph_report.get("audit_continuation_frontier_v3", [])
        if isinstance(item, dict)
    ]
    audit_continuation_pending = any(
        str(item.get("selection_status") or "")
        == "DEFERRED_PENDING_AUDIT_BUDGET"
        for item in audit_continuation_frontier
    )
    audit_frontier_resume_state = (
        graph_report.get("audit_frontier_resume_state_v3")
        if isinstance(graph_report.get("audit_frontier_resume_state_v3"), dict)
        else {}
    )
    audit_checkpoint = (
        semantic_audit_checkpoint
        if isinstance(semantic_audit_checkpoint, dict)
        else {}
    )
    checkpointed_audits = (
        audit_checkpoint.get("semantic_audit_results")
        if isinstance(audit_checkpoint.get("semantic_audit_results"), dict)
        else {}
    )
    audited: list[dict[str, Any]] = []
    if discovered and callable(on_semantic_audit_started):
        on_semantic_audit_started(
            {
                "candidate_count": len(discovered),
                "checkpointed_candidate_count": len(checkpointed_audits),
            }
        )
    for candidate_index, item in enumerate(discovered, start=1):
        candidate_identity, candidate_fingerprint = (
            _tanxi_semantic_candidate_identity_and_fingerprint(item)
        )
        checkpointed = checkpointed_audits.get(candidate_identity)
        cached_candidate = (
            _hydrate_tanxi_semantic_audit_checkpoint(
                item,
                checkpointed.get("semantic_audit_projection"),
            )
            if isinstance(checkpointed, dict)
            and str(checkpointed.get("candidate_fingerprint") or "")
            == candidate_fingerprint
            else None
        )
        progress = {
            "candidate_index": candidate_index,
            "candidate_count": len(discovered),
            "candidate_fingerprint": candidate_fingerprint,
            "reused": cached_candidate is not None,
        }
        if callable(on_semantic_candidate_started):
            on_semantic_candidate_started(candidate_identity, progress)
        if isinstance(cached_candidate, dict):
            audited.append(copy.deepcopy(cached_candidate))
            continue
        audited_candidate = audit_gap_candidate_semantics(
            project,
            item,
            positive_auditor=semantic_auditor,
            red_team_auditor=red_team_auditor,
        )
        audited.append(audited_candidate)
        if callable(on_semantic_candidate_complete):
            on_semantic_candidate_complete(
                candidate_identity,
                {
                    **progress,
                    "audited_candidate": audited_candidate,
                },
            )
    routed = [plan_targeted_retrieval(project, item) for item in audited]
    routed = [bind_candidate_to_graph_snapshot(item, snapshot) for item in routed]
    route_order = {
        GapRoute.PRIMARY_CANDIDATE.value: 0,
        GapRoute.TARGETED_RETRIEVAL.value: 1,
        GapRoute.SECONDARY_RESEARCH.value: 2,
        GapRoute.DIAGNOSTIC.value: 3,
        GapRoute.REJECT.value: 4,
    }
    routed.sort(
        key=lambda item: (
            route_order.get(str(assessment_of(item).get("route") or ""), 9),
            str(assessment_of(item).get("gap_type") or ""),
            str(item.get("candidate_identity") or ""),
        )
    )
    canonical_routed = list(routed)
    routed = _select_tanxi_display_candidates_v3(routed, max_candidates=max_gaps)
    for index, item in enumerate(routed):
        binding = item.get("graph_binding_audit") if isinstance(item.get("graph_binding_audit"), dict) else {}
        if assessment_of(item).get("route") == GapRoute.TARGETED_RETRIEVAL.value and binding.get("status") != "PASSED":
            assessment = dict(assessment_of(item))
            assessment.update(
                {
                    "route": GapRoute.TARGETED_RETRIEVAL.value,
                    "evidence_maturity": "SEMANTICALLY_VALIDATED",
                    "decision_reasons": ["GRAPH_ASSERTION_SPAN_EVIDENCE_LINK_BINDING_REQUIRED"],
                    "missing_evidence_axes": ["canonical_assertion_span_evidence_link_binding"],
                }
            )
            plan = item.get("retrieval_plan") if isinstance(item.get("retrieval_plan"), dict) else {}
            if plan.get("schema_version") == "gap_search_plan_v3":
                plan = {
                    **plan,
                    "recovery_requirements": sorted({
                        *[str(value) for value in plan.get("recovery_requirements", []) if str(value)],
                        "canonical_assertion_span_evidence_link_binding",
                    }),
                }
                item["retrieval_plan"] = plan
            routed[index] = synchronize_candidate_surface(item, assessment)
    routed, gap_resolution_work_items, gap_resolution_diagnostics = (
        build_gap_resolution_work_items_v3(
            project,
            snapshot,
            routed,
            [
                item
                for item in graph_report.get("branch_states", [])
                if isinstance(item, dict)
            ],
        )
    )
    # A provider may advance one owned V3 work item in the same TanXi run.
    # Its result is never interpreted as an old generic retrieval cycle: the
    # application boundary checks the work item, result, graph snapshot, and
    # lifecycle state before any rebind can occur.
    if callable(targeted_retrieval_executor):
        for index, item in enumerate(list(routed)):
            if assessment_of(item).get("route") != GapRoute.TARGETED_RETRIEVAL.value:
                continue
            work_item = item.get("retrieval_work_item_v3") if isinstance(item.get("retrieval_work_item_v3"), dict) else {}
            if work_item.get("schema_version") != "retrieval_work_item_v3":
                continue
            execution = targeted_retrieval_executor(item, work_item)
            applied = apply_gap_resolution_retrieval_cycle_v3(
                project,
                item,
                work_item,
                execution,
                positive_auditor=semantic_auditor,
                red_team_auditor=red_team_auditor,
            )
            completed_candidate = applied.get("candidate")
            if not isinstance(completed_candidate, dict):
                raise ValueError("GAP_RESOLUTION V3 application did not return a candidate")
            completed_candidate["retrieval_work_item_v3"] = work_item
            completed_candidate["gap_resolution_retrieval"] = dict(
                applied.get("retrieval_state") or {}
            )
            routed[index] = completed_candidate
            work_item_id = str(work_item.get("work_item_id") or "")
            for queue_item in gap_resolution_work_items:
                if str(queue_item.get("work_item_id") or "") == work_item_id:
                    queue_item["execution_state"] = dict(applied.get("retrieval_state") or {})
                    break
    primary_research = [item for item in routed if is_primary_research_candidate(item)]
    primary_mechanism = [item for item in routed if is_primary_mechanism_candidate(item)]
    # Graph-binding is an additional source-provenance gate.  A candidate
    # whose text unit cannot be joined to one explicit assertion and one
    # question-relative EvidenceLink remains visible, but cannot form a
    # primary package until extraction/retrieval repairs that join.
    primary_research = [
        item for item in primary_research
        if (item.get("graph_binding_audit") or {}).get("status") == "PASSED"
    ]
    primary_mechanism = [
        item for item in primary_mechanism
        if (item.get("graph_binding_audit") or {}).get("status") == "PASSED"
    ]
    research_packages = build_research_packages(project, primary_research)
    package_candidate_dispatch = select_research_package_candidates(project, routed)
    targeted_retrieval = [
        item for item in routed
        if assessment_of(item).get("route") == GapRoute.TARGETED_RETRIEVAL.value
    ]
    secondary_research = [
        item for item in routed
        if assessment_of(item).get("route") == GapRoute.SECONDARY_RESEARCH.value
    ]
    diagnostic_candidates = [
        item for item in routed
        if assessment_of(item).get("route") in {GapRoute.DIAGNOSTIC.value, GapRoute.REJECT.value}
    ]
    diagnostics = [
        *[item for item in graph_report.get("diagnostics", []) if isinstance(item, dict)],
        *gap_resolution_diagnostics,
    ]
    slot_directed_recovery_plans: list[dict[str, Any]] = []
    for branch in graph_report.get("branch_states", []):
        if not isinstance(branch, dict):
            continue
        missing_slots = branch.get("missing_direct_slot_ids")
        if not isinstance(missing_slots, list) or not any(str(item).strip() for item in missing_slots):
            continue
        if branch.get("slot_directed_retrieval_allowed") is not True:
            diagnostics.append({
                "stage": "failure_specific_recovery_routing",
                "sub_hypothesis_id": str(branch.get("sub_hypothesis_id") or ""),
                "reason": "SLOT_DIRECTED_RETRIEVAL_SUPPRESSED_FOR_NON_SHORTAGE_FAILURE",
                "failure_type": str(branch.get("recovery_failure_type") or ""),
                "next_action": str(branch.get("next_action") or ""),
            })
            continue
        try:
            slot_directed_recovery_plans.append(
                build_slot_directed_recovery_plan(project, branch)
            )
        except ValueError as exc:
            diagnostics.append({
                "stage": "slot_directed_recovery_planning",
                "sub_hypothesis_id": str(branch.get("sub_hypothesis_id") or ""),
                "reason": "SLOT_DIRECTED_RECOVERY_PLAN_REJECTED",
                "detail": str(exc),
            })
    handoffs = _source_bound_subhypothesis_handoffs(graph_report, routed)
    evidence_graph = graph_report.get("evidence_graph") if isinstance(graph_report.get("evidence_graph"), dict) else {}
    unlinked_source_records = [
        item for item in evidence_graph.get("unlinked_source_records", [])
        if isinstance(item, dict)
    ]
    ledger = {
        str(item.get("candidate_identity") or item.get("gap_id") or ""): {
            "gap_id": str(item.get("gap_id") or ""),
            "sub_hypothesis_ids": list(item.get("sub_hypothesis_ids") or []),
            "gap_type": str(assessment_of(item).get("gap_type") or ""),
            "gap_subtype": str(assessment_of(item).get("gap_subtype") or ""),
            "assessment_version": int(item.get("assessment_version") or 0),
            "retrieval_version": int(item.get("retrieval_version") or 0),
            "package_version": int(item.get("package_version") or 0),
            "candidate_stage": str(assessment_of(item).get("candidate_stage") or ""),
            "semantic_verdict": str(assessment_of(item).get("semantic_verdict") or ""),
            "evidence_maturity": str(assessment_of(item).get("evidence_maturity") or ""),
            "scope_status": str(assessment_of(item).get("scope_status") or ""),
            "route": str(assessment_of(item).get("route") or ""),
            "decision_reasons": list(assessment_of(item).get("decision_reasons") or []),
            "gap_resolution_retrieval": dict(item.get("gap_resolution_retrieval") or {}),
            "gap_resolution_work_item_id": str(
                (item.get("retrieval_work_item_v3") or {}).get("work_item_id") or ""
            ),
            "source_unit_ids": [
                str(unit.get("source_unit_id") or "")
                for unit in item.get("source_evidence_units", [])
                if isinstance(unit, dict)
            ],
        }
        for item in routed
    }
    verification_tasks = [
        {
            "task_type": "TYPE_SPECIFIC_GAP_AUDIT_OR_RETRIEVAL",
            "candidate_identity": str(item.get("candidate_identity") or ""),
            "gap_id": str(item.get("gap_id") or ""),
            "gap_type": str(assessment_of(item).get("gap_type") or ""),
            "route": str(assessment_of(item).get("route") or ""),
            "required_upstream_action": (
                "run_declared_type_directed_retrieval"
                if assessment_of(item).get("route") == GapRoute.TARGETED_RETRIEVAL.value
                else "repair_type_payload_or_source_span_semantics"
            ),
            "retrieval_pending": assessment_of(item).get("route") == GapRoute.TARGETED_RETRIEVAL.value,
            "gap_resolution_work_item_id": str(
                (item.get("retrieval_work_item_v3") or {}).get("work_item_id") or ""
            ),
            "target_slot_ids": list(
                (item.get("gap_resolution_retrieval") or {}).get("target_slot_ids") or []
            ),
            "missing_obligation_slot_ids": list(
                (item.get("gap_resolution_retrieval") or {}).get("missing_obligation_slot_ids") or []
            ),
            "retrieval_status": str(
                (item.get("gap_resolution_retrieval") or {}).get("status") or ""
            ),
            "retrieval_stage": str(
                (item.get("gap_resolution_retrieval") or {}).get("stage") or ""
            ),
            "retrieval_reason_code": str(
                (item.get("gap_resolution_retrieval") or {}).get("reason_code") or ""
            ),
            "may_enter_socrates": False,
        }
        for item in routed
        if not is_primary_research_candidate(item)
    ] + [
        {
            "task_type": "SOURCE_BOUND_GAP_RECOVERY",
            "sub_hypothesis_id": str(item.get("sub_hypothesis_id") or ""),
            "status": str(item.get("state") or ""),
            "first_blocking_stage": str(item.get("first_blocking_stage") or ""),
            "required_upstream_action": str(item.get("next_action") or ""),
            "may_enter_socrates": False,
        }
        for item in graph_report.get("branch_states", [])
        if isinstance(item, dict) and str(item.get("state") or "") != "GAP_CANDIDATES_DISCOVERED"
    ]
    summary = graph_report.get("summary") if isinstance(graph_report.get("summary"), dict) else {}
    detector_execution_metrics = (
        dict(summary.get("detector_execution_metrics") or {})
    )
    candidate_funnel = {
        "schema_version": "tanxi_gap_funnel_v3",
        "source_span_count": int(summary.get("source_span_count") or 0),
        "explicit_assertion_count": int(summary.get("detector_admitted_assertion_count") or 0),
        "all_contract_bound_assertion_count": int(summary.get("all_contract_bound_assertion_count") or summary.get("explicit_assertion_count") or 0),
        "background_assertion_count": int(summary.get("background_assertion_count") or 0),
        "derived_inference_count": int(summary.get("detector_admitted_derived_inference_count") or 0),
        "unlinked_source_record_count": int(summary.get("unlinked_source_record_count") or 0),
        "artifact_integrity_error_count": int(
            workflow_integrity.get("artifact_integrity_error_count") or 0
        ),
        "candidate_count": len(routed),
        "audited_candidate_count": len(canonical_routed),
        "display_candidate_count": len(routed),
        "detected_candidate_count": int(
            summary.get("detected_candidate_count") or len(canonical_routed)
        ),
        "audit_continuation_candidate_count": int(
            summary.get("audit_continuation_candidate_count") or 0
        ),
        "candidate_count_by_type": dict(Counter(str(assessment_of(item).get("gap_type") or "") for item in routed)),
        "candidate_count_by_stage": dict(Counter(str(assessment_of(item).get("candidate_stage") or "") for item in routed)),
        "candidate_count_by_route": dict(Counter(str(assessment_of(item).get("route") or "") for item in routed)),
        "primary_research_candidate_count": len(primary_research),
        "primary_mechanism_candidate_count": len(primary_mechanism),
        "targeted_retrieval_candidate_count": len(targeted_retrieval),
        "secondary_research_candidate_count": len(secondary_research),
        "diagnostic_candidate_count": len(diagnostic_candidates),
        "diagnostic_count": int(summary.get("diagnostic_count") or 0),
        "slot_directed_recovery_plan_count": len(slot_directed_recovery_plans),
        "gap_resolution_work_item_count": len(gap_resolution_work_items),
        "gap_resolution_slot_binding_blocked_count": len([
            item for item in gap_resolution_diagnostics
            if str(item.get("reason_code") or "") == "GAP_RESOLUTION_SLOT_BINDING_REQUIRED"
        ]),
        "first_failure_counts": dict(Counter(
            str(item.get("reason") or item.get("stage") or "UNSPECIFIED_DIAGNOSTIC")
            for item in diagnostics
        )),
        "detector_execution_metrics": detector_execution_metrics,
    }
    log_event(
        "SCIENCE",
        "tanxi_type_directed_gap_analysis_complete",
        project_id=str(project.get("project_id") or ""),
        source_spans=candidate_funnel["source_span_count"],
        explicit_assertions=candidate_funnel["explicit_assertion_count"],
        derived_inferences=candidate_funnel["derived_inference_count"],
        unlinked_source_records=candidate_funnel["unlinked_source_record_count"],
        gap_types=candidate_funnel["candidate_count_by_type"],
        routes=candidate_funnel["candidate_count_by_route"],
        detector_worker_count=int(detector_execution_metrics.get("worker_count") or 0),
        detector_context_build_elapsed_ms=float(
            detector_execution_metrics.get("context_build_elapsed_ms") or 0.0
        ),
        detector_execution_elapsed_ms=float(
            detector_execution_metrics.get("detector_execution_elapsed_ms") or 0.0
        ),
    )
    for branch in graph_report.get("branch_states", []) if isinstance(graph_report.get("branch_states"), list) else []:
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("sub_hypothesis_id") or "")
        branch_candidates = [
            item for item in routed
            if branch_id in list(item.get("sub_hypothesis_ids") or [])
        ]
        log_event(
            "SCIENCE",
            "gap_analysis_summary",
            project_id=str(project.get("project_id") or ""),
            sub_hypothesis_id=branch_id,
            retrieval_execution_status=str(branch.get("retrieval_execution_status") or "NOT_EXECUTED"),
            current_contract_admitted_assertion_count=int(branch.get("current_contract_admitted_assertion_count") or 0),
            background_assertion_count=int(branch.get("background_assertion_count") or 0),
            typed_slot_admitted_source_count=int(branch.get("typed_slot_admitted_source_count") or 0),
            required_direct_slot_ids=list(branch.get("required_direct_slot_ids") or []),
            covered_direct_slot_ids=list(branch.get("covered_direct_slot_ids") or []),
            missing_direct_slot_ids=list(branch.get("missing_direct_slot_ids") or []),
            candidate_gaps_by_type=dict(Counter(str(assessment_of(item).get("gap_type") or "") for item in branch_candidates)),
            candidate_routes=dict(Counter(str(assessment_of(item).get("route") or "") for item in branch_candidates)),
            accepted_gap_count=len(branch_candidates),
            terminal_state=str(branch.get("state") or ""),
            first_blocking_stage=str(branch.get("first_blocking_stage") or ""),
            recommended_action=str(branch.get("next_action") or ""),
        )
    return {
        "agent": "tanxi",
        "schema_version": "tanxi_gap_report_v3",
        "thought": (
            "TanXi treated evidence-graph output as discovery leads, classified each lead by a scientific-gap contract, "
            "audited source-span entailment, and routed it to diagnostic repair, type-directed retrieval, or a qualified research package."
        ),
        "ranked_gaps": routed,
        "audit_continuation_frontier_v3": audit_continuation_frontier,
        "audit_frontier_resume_state_v3": dict(audit_frontier_resume_state),
        "audit_continuation_pending": audit_continuation_pending,
        "primary_research_candidates": primary_research,
        "primary_mechanism_candidates": primary_mechanism,
        "research_packages": research_packages,
        "research_packages_by_kind": group_research_packages_by_kind(research_packages),
        "research_package_candidate_dispatch": package_candidate_dispatch,
        "targeted_retrieval_candidates": targeted_retrieval,
        "gap_resolution_work_items_v3": gap_resolution_work_items,
        "slot_directed_recovery_plans": slot_directed_recovery_plans,
        "secondary_research_candidates": secondary_research,
        "diagnostic_candidates": diagnostic_candidates,
        "subhypothesis_gap_handoffs": handoffs,
        "verification_tasks": verification_tasks,
        "gap_candidate_ledger": ledger,
        "tanxi_candidate_funnel": candidate_funnel,
        "detector_execution_metrics": detector_execution_metrics,
        "evidence_graph": graph_report.get("evidence_graph", {}),
        "research_evidence_graph_ref": snapshot_ref,
        "research_evidence_graph_quality": dict(snapshot.get("quality_audit") or {}),
        "research_evidence_graph_workflow_integrity": workflow_integrity,
        "branch_gap_states": graph_report.get("branch_states", []),
        "diagnostics": diagnostics,
        "evidence_extraction_shortages": unlinked_source_records[:max_gaps],
        "rejected_scientific_candidates": diagnostic_candidates + diagnostics[:max_gaps],
        "candidate_pools": {
            "by_gap_type": group_by_gap_type(routed),
            "by_semantic_status": group_by_semantic_status(routed),
            "by_route": group_by_route(routed),
            "research_packages_by_kind": group_research_packages_by_kind(research_packages),
            "evidence_extraction_shortages": unlinked_source_records[:max_gaps],
        },
        "candidate_filter": {
            "source_span_and_assertion_lineage_required": True,
            "type_contract_required": True,
            "semantic_audit_required": True,
            "retrieval_assessment_required_for_primary": True,
            "input_candidate_count": len(discovered),
            "audited_candidate_count": len(canonical_routed),
            "display_candidate_count": len(routed),
            "audit_candidate_budget_per_type_contract": int(
                summary.get("audit_candidate_budget_per_type_contract") or 6
            ),
            "unlinked_source_record_count": len(unlinked_source_records),
            "diagnostic_count": len(diagnostics),
            "slot_directed_recovery_requires_explicit_missing_slots": True,
            "gap_resolution_requires_candidate_slot_snapshot_work_item": True,
        },
    }


def _compact_tanxi_ranked_gap(candidate: dict[str, Any]) -> dict[str, Any]:
    """Keep a ranked candidate's decision and provenance references, not quotes."""
    item = _tanxi_reference_only_value(candidate) if isinstance(candidate, dict) else {}
    source_units = [
        unit
        for unit in item.get("source_evidence_units", [])
        if isinstance(unit, dict)
    ]
    item["source_evidence_units"] = [
        {
            key: copy.deepcopy(unit[key])
            for key in (
                "paper_id",
                "document_version_hash",
                "source_unit_id",
                "source_span_id",
                "assertion_id",
                "evidence_assertion_id",
                "evidence_link_id",
                "excerpt_hash",
                "quote_hash",
                "source_field",
                "binding_status",
                "graph_binding_status",
            )
            if key in unit
        }
        for unit in source_units
    ]
    item["semantic_audit"] = _tanxi_semantic_audit_reference_projection(
        item.get("semantic_audit")
    )
    if isinstance(item.get("semantic_assessment"), dict):
        item["semantic_assessment"] = _tanxi_semantic_assessment_reference_projection(
            item["semantic_assessment"]
        )
    item["payload_policy"] = {
        "source_evidence_units": "reference_only_no_excerpt",
        "semantic_audit": "source_ids_hashes_offsets_and_verdicts_only",
        "hydrate_from": "research_evidence_graph_ref_and_evidence_registries",
    }
    return item


def compact_tanxi_gap_report(report: dict[str, Any]) -> dict[str, Any]:
    """Expose and persist TanXi results by graph reference, not graph copies.

    Ranked candidates remain available because GroupChat routing needs their
    source-bound decisions.  The immutable graph and duplicate candidate
    pools are already addressable through ``research_evidence_graph_ref`` and
    must not be copied into each tool response or project snapshot.
    """
    source = report if isinstance(report, dict) else {}
    graph = source.get("evidence_graph") if isinstance(source.get("evidence_graph"), dict) else {}
    graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    funnel = source.get("tanxi_candidate_funnel") if isinstance(source.get("tanxi_candidate_funnel"), dict) else {}
    compact = {
        key: value
        for key, value in source.items()
        if key not in {"evidence_graph", "candidate_pools"}
    }
    compact["ranked_gaps"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("ranked_gaps", [])
        if isinstance(item, dict)
    ]
    compact["primary_research_candidates"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("primary_research_candidates", [])
        if isinstance(item, dict)
    ]
    compact["primary_mechanism_candidates"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("primary_mechanism_candidates", [])
        if isinstance(item, dict)
    ]
    compact["targeted_retrieval_candidates"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("targeted_retrieval_candidates", [])
        if isinstance(item, dict)
    ]
    compact["gap_resolution_work_items_v3"] = [
        {
            key: copy.deepcopy(item[key])
            for key in (
                "schema_version",
                "work_item_id",
                "work_item_kind",
                "project_id",
                "sub_hypothesis_id",
                "research_question_contract_id",
                "research_question_contract_revision",
                "gap_candidate_id",
                "gap_candidate_fingerprint",
                "gap_type",
                "target_slot_ids",
                "obligations",
                "required_source_roles",
                "required_evidence_modes",
                "plan_fingerprint",
                "graph_snapshot_id",
                "execution_state",
            )
            if key in item
        }
        for item in source.get("gap_resolution_work_items_v3", [])
        if isinstance(item, dict)
    ]
    compact["secondary_research_candidates"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("secondary_research_candidates", [])
        if isinstance(item, dict)
    ]
    compact["diagnostic_candidates"] = [
        _compact_tanxi_ranked_gap(item)
        for item in source.get("diagnostic_candidates", [])
        if isinstance(item, dict)
    ]
    compact["evidence_graph"] = {
        "schema_version": str(graph.get("schema_version") or "heterogeneous_evidence_graph_v2"),
        "projection_source": str(graph.get("projection_source") or RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION),
        "summary": dict(graph_summary),
        "graph_ref": dict(source.get("research_evidence_graph_ref") or {}),
        "payload_policy": "reference_first_no_source_spans_assertions_or_derived_inferences",
    }
    compact["candidate_pools"] = {
        "schema_version": "tanxi_candidate_pool_index_v2",
        "ranked_gap_count": len(compact.get("ranked_gaps") or []),
        "candidate_count_by_type": dict(funnel.get("candidate_count_by_type") or {}),
        "candidate_count_by_route": dict(funnel.get("candidate_count_by_route") or {}),
        "research_package_count": len(compact.get("research_packages") or []),
        "payload_policy": "ranked_objects_are_canonical; duplicate_group_payloads_omitted",
    }
    return compact


def direct_gap_signal_assessment(gap: dict[str, Any]) -> dict[str, Any]:
    """Expose v2 provenance for legacy diagnostic consumers.

    This function no longer performs lexical or graph-topology inference.  It
    deliberately reads the already-authoritative v2 assessment so no caller
    can turn an ``unknown`` phrase, a path shape, or a historical signal field
    into a new eligibility path.
    """
    assessment = assessment_of(gap)
    units = [item for item in gap.get("source_evidence_units", []) if isinstance(item, dict)]
    source_located = bool(units) and all(
        str(item.get("paper_id") or "")
        and str(item.get("source_unit_id") or "")
        and str(item.get("binding_status") or "") == "SOURCE_UNIT_VERIFIED"
        for item in units
    )
    semantic_verdict = str(assessment.get("semantic_verdict") or "")
    gap_type = str(assessment.get("gap_type") or "")
    direct = bool(source_located and semantic_verdict == SemanticVerdict.ENTAILED.value)
    mechanistic = bool(
        direct
        and gap_type == GapType.CAUSAL_IDENTIFICATION.value
    )
    return {
        "present": direct,
        "mechanistic": mechanistic,
        "source_located": source_located,
        "signal_type": str(assessment.get("signal_type") or ""),
        "confidence": normalize_semantic_confidence(
            assessment.get("semantic_confidence")
        ),
        "markers": [],
        "gap_predicate": {
            "schema_version": "gap_assessment_projection_v2",
            "semantic_verdict": semantic_verdict,
            "gap_type": gap_type,
        },
    }


def classify_scientific_gap_track(gap: dict[str, Any]) -> dict[str, Any]:
    """Return the workflow track encoded by a v2 gap assessment.

    This is intentionally a projection of the typed assessment, rather than a
    second eligibility policy.  A source-bound graph edge, a lexical label, or
    a historical status label cannot grant a primary route here.
    """
    assessment = assessment_of(gap)
    direct_signal = direct_gap_signal_assessment(gap)
    route = str(assessment.get("route") or "")
    gap_type = str(assessment.get("gap_type") or "")
    if route == GapRoute.PRIMARY_CANDIDATE.value:
        mechanism_ready = is_primary_mechanism_candidate(gap)
        return {
            "track": "PRIMARY_MECHANISM_CANDIDATE" if mechanism_ready else "PRIMARY_RESEARCH_CANDIDATE",
            "eligible_for_hypothesis_generation": mechanism_ready,
            "eligible_for_research_package": True,
            "reason": "The type contract, semantic audit, scope gate, retrieval assessment, and design-readiness gate passed.",
            "direct_gap_signal": direct_signal,
        }
    if route == GapRoute.TARGETED_RETRIEVAL.value:
        return {
            "track": "TARGETED_RETRIEVAL",
            "eligible_for_hypothesis_generation": False,
            "eligible_for_research_package": False,
            "reason": "The candidate is semantically entailed but requires its declared type-directed retrieval before qualification.",
            "direct_gap_signal": direct_signal,
        }
    if route == GapRoute.SECONDARY_RESEARCH.value:
        return {
            "track": "SECONDARY_RESEARCH",
            "eligible_for_hypothesis_generation": False,
            "eligible_for_research_package": False,
            "reason": "The candidate remains useful for secondary investigation but does not satisfy its primary type contract.",
            "direct_gap_signal": direct_signal,
        }
    if route == GapRoute.REJECT.value:
        return {
            "track": "REJECTED",
            "eligible_for_hypothesis_generation": False,
            "eligible_for_research_package": False,
            "reason": "Source evidence or post-retrieval evidence disqualifies the declared scientific gap.",
            "direct_gap_signal": direct_signal,
        }
    return {
        "track": "DIAGNOSTIC",
        "eligible_for_hypothesis_generation": False,
        "eligible_for_research_package": False,
        "reason": "Candidate discovery, source binding, or semantic audit is incomplete; no scientific-gap claim is authorized.",
        "direct_gap_signal": direct_signal,
    }


def mechanistic_priority_assessment(
    project: dict[str, Any],
    gap: dict[str, Any],
    alignment: list[dict[str, Any]],
    relevance: dict[str, Any],
) -> dict[str, Any]:
    triage = classify_scientific_gap_track(gap)
    gap_type = str(gap.get("gap_type") or "")
    direct_signal = triage["direct_gap_signal"]
    causal_bottleneck = 1.0 if gap_type in {"causal_chain_break", "causal_mediation_unresolved", "edge_specific_unknown", "measurement_gap"} or gap.get("causal_gap") or gap.get("causal_mediation") else 0.0
    contradiction_or_anomaly = 1.0 if gap_type in {"contradiction", "conflict_boundary_gap", "anomaly", "theory_observation_mismatch"} else 0.0
    if gap_type == "implicit_tabi" and isinstance(gap.get("tabi_checks"), dict) and gap["tabi_checks"].get("substantive"):
        contradiction_or_anomaly = 1.0
    references = [ref for ref in gap.get("supporting_references", []) if ref]
    reference_strength = min(1.0, len(references) / 3.0)
    semantic = gap.get("semantic_plausibility") if isinstance(gap.get("semantic_plausibility"), dict) else {}
    semantic_verdict = str(semantic.get("verdict") or "PASS")
    context_strength = 1.0 if semantic_verdict == "PASS" else 0.55 if semantic_verdict == "HUMAN_REVIEW" else 0.0
    causal_mediation = gap.get("causal_mediation") if isinstance(gap.get("causal_mediation"), dict) else {}
    mediation_confidence = causal_mediation.get("confidence") if isinstance(causal_mediation.get("confidence"), dict) else {}
    direct_evidence = float(mediation_confidence.get("chain_strength") or 0.0)
    if not direct_evidence and gap_type == "causal_chain_break":
        direct_evidence = 0.45
    records = mechanism_core_records(project)
    quality_values: list[float] = []
    for record in records:
        if str(record_reference(record)) not in references:
            continue
        quality = record.get("publication_quality_score")
        if isinstance(quality, (int, float)):
            quality_values.append(max(0.0, min(1.0, float(quality))))
        elif str(record.get("venue") or "").lower() in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}:
            quality_values.append(0.45)
        else:
            quality_values.append(0.65)
    source_reliability = sum(quality_values) / len(quality_values) if quality_values else 0.5
    evidence_strength = min(
        1.0,
        0.20 * reference_strength
        + 0.30 * float(relevance.get("score") or 0.0)
        + 0.20 * context_strength
        + 0.15 * direct_evidence
        + 0.15 * source_reliability,
    )
    strategic_score = max((float(item.get("alignment_score") or 0.0) / 10.0 for item in alignment), default=0.0)
    impact = min(1.0, 0.6 * strategic_score + 0.4 * {"high": 1.0, "medium": 0.55, "low": 0.2}.get(str(gap.get("application_value") or "medium"), 0.55))
    components = {
        "direct_gap_signal": 1.0 if direct_signal["present"] else 0.0,
        "causal_bottleneck": causal_bottleneck,
        "contradiction_or_anomaly": contradiction_or_anomaly,
        "evidence_strength_and_context_match": evidence_strength,
        "scientific_or_strategic_impact": impact,
    }
    weighted = sum(MECHANISTIC_PRIORITY_WEIGHTS[name] * value for name, value in components.items())
    penalties: list[dict[str, Any]] = []
    penalty = 0.0
    if semantic_verdict == "REJECT":
        penalties.append({"name": "cross_domain_incompatibility", "value": 0.25})
        penalty += 0.25
    elif semantic_verdict == "HUMAN_REVIEW":
        penalties.append({"name": "context_not_confirmed", "value": 0.10})
        penalty += 0.10
    if not references:
        penalties.append({"name": "missing_source_reference", "value": 0.20})
        penalty += 0.20
    if triage["track"] == "SECONDARY_RESEARCH_OPPORTUNITY":
        matrix_auxiliary = min(
            MECHANISTIC_PRIORITY_MATRIX_AUXILIARY_CAP,
            0.02 + 0.01 * min(3, len(references)),
        )
        return {
            "track": triage["track"],
            "components": components,
            "evidence_detail": {
                "reference_strength": round(reference_strength, 3),
                "core_context_relevance": round(float(relevance.get("score") or 0.0), 3),
                "semantic_context_match": round(context_strength, 3),
                "direct_evidence_strength": round(direct_evidence, 3),
                "source_reliability": round(source_reliability, 3),
            },
            "penalties": penalties + [{"name": "matrix_or_coverage_only", "value": 1.0 - matrix_auxiliary}],
            "mechanistic_priority": round(matrix_auxiliary * 10.0, 3),
            "matrix_auxiliary_weight": round(matrix_auxiliary, 3),
            "reason": triage["reason"],
        }
    score = max(0.0, weighted - penalty)
    return {
        "track": triage["track"],
        "components": components,
        "evidence_detail": {
            "reference_strength": round(reference_strength, 3),
            "core_context_relevance": round(float(relevance.get("score") or 0.0), 3),
            "semantic_context_match": round(context_strength, 3),
            "direct_evidence_strength": round(direct_evidence, 3),
            "source_reliability": round(source_reliability, 3),
        },
        "penalties": penalties,
        "mechanistic_priority": round(score * 10.0, 3),
        "matrix_auxiliary_weight": 0.0,
        "reason": triage["reason"],
    }


def mechanism_core_records(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the evidence corpus eligible to support a scientific mechanism.

    This is deliberately domain-agnostic.  Serial retrieval labels boundary
    extensions, while the generic domain reviewer labels marginal imports. Both
    remain visible in a landscape report but cannot define a mechanism gap.
    """
    try:
        from ._pipeline import project_records_for_mapping
    except ImportError:
        from _pipeline import project_records_for_mapping
    records = project_records_for_mapping(project)
    # Once a project has scoped sub-hypothesis contracts, only records that
    # passed the same contract may define a causal gap.  We intentionally do
    # not fall back to legacy records in that state: doing so would revive the
    # very cross-topic drift the import gate just rejected.
    alignment_enforced = bool(project.get("subhypothesis_alignment_contracts"))
    core = [
        record for record in records
        if str(record.get("retrieval_phase") or "") != "boundary_extension"
        and str(record.get("domain_review_verdict") or "keep") not in {"review", "reject"}
        and (
            not alignment_enforced
            or bool((record.get("alignment_assessment") or {}).get("core_eligible"))
        )
    ]
    return core


def mechanism_entity_profile(project: dict[str, Any]) -> dict[str, Any]:
    """Build a project-local entity boundary from core PaperGraph evidence."""
    try:
        from ._literature_search import query_terms
        from ._utils import unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import unique_preserve_order
    records = mechanism_core_records(project)
    counts: Counter[str] = Counter()
    labels: list[str] = []
    for record in records:
        labels.extend(
            str(record.get(field) or "")
            for field in ("method", "scenario", "benchmark")
            if str(record.get(field) or "").strip()
        )
        text = " ".join(str(record.get(field) or "") for field in (
            "title", "abstract", "method", "scenario", "benchmark", "contribution", "limitation", "conclusion",
        ))
        for term in query_terms(text):
            if len(term) >= 4 and term not in _MECHANISM_NOISE_TERMS:
                counts[term] += 1
    entities = [term for term, _ in counts.most_common(100)]
    return {
        "entities": entities,
        "labels": unique_preserve_order(labels)[:80],
        "record_count": len(records),
        "source": "active_core_papergraph",
    }


def mechanism_gap_relevance(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Score whether a gap is grounded in the project's core evidence corpus."""
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    profile = mechanism_entity_profile(project)
    gap_text = " ".join(
        str(gap.get(field) or "") for field in ("description", "gap_description", "value_argument", "suggested_research_path")
    )
    ingredients = gap.get("hypothesis_ingredients") if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    gap_text += " " + " ".join(str(value) for values in ingredients.values() for value in (values if isinstance(values, list) else [values]))
    terms = [term for term in query_terms(gap_text) if len(term) >= 4 and term not in _MECHANISM_NOISE_TERMS]
    core_entities = set(profile["entities"])
    label_text = " ".join(profile["labels"]).lower()
    entity_hits = [term for term in terms if term in core_entities]
    label_hits = [term for term in terms if term in label_text]
    denominator = max(3, min(12, len(set(terms))))
    score = min(1.0, (len(set(entity_hits)) + 0.5 * len(set(label_hits))) / denominator)
    semantic = gap.get("semantic_plausibility") if isinstance(gap.get("semantic_plausibility"), dict) else {}
    verdict = str(semantic.get("verdict") or "")
    triage = classify_scientific_gap_track(gap)
    eligible = bool(triage["eligible_for_hypothesis_generation"]) and score >= 0.34 and verdict != "REJECT"
    return {
        "score": round(score, 3),
        "eligible_for_mechanism_hypothesis": eligible,
        "core_entity_hits": sorted(set(entity_hits))[:12],
        "profile_record_count": profile["record_count"],
        "gap_track": triage["track"],
        "reason": (
            "Gap is grounded in core mechanism evidence."
            if eligible else "Gap is weakly connected to core mechanism evidence or relies on an unverified cross-domain transfer."
        ),
    }


def select_mechanism_hypothesis_gaps(project: dict[str, Any], gaps: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Choose only qualified causal candidates for a mechanism package.

    Non-causal gap types are first-class research-package candidates, but they
    never enter a causal hypothesis package by being relabelled as mechanisms.
    Historical graph states and lexical relevance scores are not eligibility
    fallbacks for this selection boundary.
    """
    scored: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        try:
            if not is_primary_mechanism_candidate(gap):
                continue
        except ValueError:
            continue
        relevance = mechanism_gap_relevance(project, gap)
        item = dict(gap)
        item["mechanism_relevance"] = relevance
        scored.append(item)
    scored.sort(key=lambda item: (-float(item.get("exploration_value_score") or 0), -float(item["mechanism_relevance"].get("score") or 0)))
    try:
        from ._hypothesis_coverage import select_compatible_mechanism_gaps
    except ImportError:
        from _hypothesis_coverage import select_compatible_mechanism_gaps
    return select_compatible_mechanism_gaps(project, scored, limit=min(3, max(1, int(limit or 3))))


def select_restricted_component_bridge_hypothesis_gaps(
    project: dict[str, Any],
    gaps: list[dict[str, Any]],
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Select capped component-bridge gaps when no primary mechanism package exists.

    The returned gaps are explicitly *not* direct-core or primary scientific
    gaps.  They can seed a restricted MingLi package whose output must be
    framed as a bridge/follow-up hypothesis requiring direct-core validation.
    """
    selected: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        is_component_bridge = bool(
            str(gap.get("gap_type") or "") == "component_bridge_gap_synthesis"
            or gap.get("component_bridge_gap_synthesis_ready") is True
            or gap.get("restricted_component_bridge_hypothesis_allowed") is True
            or str(gap.get("gap_track") or "") == "COMPONENT_BRIDGE_GAP_SYNTHESIS"
        )
        if not is_component_bridge:
            continue
        if not restricted_component_bridge_role_contract_ready(gap):
            continue
        item = mark_restricted_component_bridge_hypothesis_policy(dict(gap))
        if not (item.get("supporting_references") or item.get("source_evidence_units")):
            item["restricted_bridge_selection_warning"] = "no_bound_source_units_or_references"
        selected.append(item)
    selected.sort(
        key=lambda item: (
            -float(item.get("exploration_value_score") or item.get("mechanistic_priority") or item.get("novelty_score") or 0.0),
            -int(bool(item.get("source_evidence_units"))),
            str(item.get("sub_hypothesis_id") or ""),
            str(item.get("gap_id") or ""),
        )
    )
    return selected[: max(1, int(limit or 1))]


def _subhypothesis_priority_lookup(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for sub_hypothesis in project.get("sub_hypotheses", []) if isinstance(project, dict) else []:
        if not isinstance(sub_hypothesis, dict):
            continue
        sub_id = str(sub_hypothesis.get("id") or "").strip()
        if not sub_id:
            continue
        annotation = (
            sub_hypothesis.get("annotation")
            if isinstance(sub_hypothesis.get("annotation"), dict)
            else sub_hypothesis.get("hypothesis_annotation")
            if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict)
            else {}
        )
        priority = (
            annotation.get("priority")
            if isinstance(annotation.get("priority"), dict)
            else sub_hypothesis.get("retrieval_priority")
            if isinstance(sub_hypothesis.get("retrieval_priority"), dict)
            else {}
        )
        if not priority:
            continue
        lookup[sub_id] = {
            "sub_hypothesis_id": sub_id,
            "tier": str(priority.get("tier") or ""),
            "overall": float(priority.get("overall") or 0.0),
            "impact": int(priority.get("impact") or 0),
            "feasibility": int(priority.get("feasibility") or 0),
            "novelty": int(priority.get("novelty") or 0),
            "strategic_alignment": int(priority.get("strategic_alignment") or 0),
            "strategy": str(priority.get("strategy") or ""),
            "evidence_standard": str(annotation.get("evidence_standard_id") or ""),
        }
    return lookup


def _gap_subhypothesis_id_candidates(gap: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        gap.get("sub_hypothesis_id"),
        gap.get("subhypothesis_id"),
        gap.get("source_sub_hypothesis_id"),
        gap.get("original_sub_hypothesis_id"),
    ]
    for key in (
        "mechanism_seed_contract",
        "gap_existence_verification",
        "original_source_role_audit",
        "original_source_role_assessment",
        "subhypothesis_context",
    ):
        nested = gap.get(key)
        if isinstance(nested, dict):
            values.extend([
                nested.get("sub_hypothesis_id"),
                nested.get("subhypothesis_id"),
                nested.get("source_sub_hypothesis_id"),
            ])
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def _parent_subhypothesis_priority_for_gap(
    project: dict[str, Any],
    gap: dict[str, Any],
    *,
    lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    priority_lookup = lookup if isinstance(lookup, dict) else _subhypothesis_priority_lookup(project)
    for sub_id in _gap_subhypothesis_id_candidates(gap):
        priority = priority_lookup.get(sub_id)
        if priority:
            return dict(priority)
    return {}


def _tanxi_rank_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    parent_priority = (
        item.get("parent_subhypothesis_priority")
        if isinstance(item.get("parent_subhypothesis_priority"), dict)
        else {}
    )
    mechanism_relevance = (
        item.get("mechanism_relevance")
        if isinstance(item.get("mechanism_relevance"), dict)
        else {}
    )
    return (
        0 if item.get("gap_candidate_pool") == PRIMARY_MECHANISM_CANDIDATE_POOL else 1,
        0 if item.get("gap_track") == "PRIMARY_SCIENTIFIC_GAP" else 1,
        -float(item.get("mechanistic_priority") or item.get("exploration_value_score") or 0.0),
        -float(parent_priority.get("overall") or item.get("parent_subhypothesis_priority_overall") or 0.0) * 0.15,
        -float(mechanism_relevance.get("score") or 0.0),
        str(item.get("gap_description") or item.get("description") or ""),
    )


def prioritize_gaps(
    project: dict[str, Any],
    raw_gaps: list[dict[str, Any]],
    coverage_analysis: dict[str, Any],
    strategic_domains: list[str],
    *,
    max_gaps: int = 10,
) -> list[dict[str, Any]]:
    try:
        from ._hypothesis_coverage import classify_gap_analysis_role
    except ImportError:
        from _hypothesis_coverage import classify_gap_analysis_role
    density_lookup = {str(item.get("topic", "")).lower(): item for item in coverage_analysis.get("density_holes", [])}
    ranked: list[dict[str, Any]] = []
    parent_priority_lookup = _subhypothesis_priority_lookup(project)
    for gap in raw_gaps:
        refs = [ref for ref in gap.get("supporting_references", []) if ref]
        if not refs:
            continue
        alignment = align_gap_with_strategic_needs(gap, strategic_domains)
        relevance = mechanism_gap_relevance(project, gap)
        priority = mechanistic_priority_assessment(project, gap, alignment, relevance)
        legacy_score, legacy_reason = tanxi_gap_priority_score(project, gap, alignment, density_lookup)
        triage = classify_scientific_gap_track(gap)
        eligible_for_hypothesis = bool(
            triage["eligible_for_hypothesis_generation"] and relevance["eligible_for_mechanism_hypothesis"]
        )
        candidate_pool = str(gap.get("gap_candidate_pool") or default_gap_candidate_pool(str(gap.get("gap_type") or "")))
        if candidate_pool != PRIMARY_MECHANISM_CANDIDATE_POOL:
            eligible_for_hypothesis = False
        item = dict(gap)  # Preserve ingredients/TABI/source signals for Socrates and MingLi.
        parent_priority = _parent_subhypothesis_priority_for_gap(
            project,
            item,
            lookup=parent_priority_lookup,
        )
        parent_priority_reason = (
            f" Parent SH priority: {parent_priority.get('tier') or 'UNRANKED'} "
            f"(overall={float(parent_priority.get('overall') or 0.0):.2f}, "
            f"standard={parent_priority.get('evidence_standard') or 'unspecified'})."
            if parent_priority
            else ""
        )
        item.update(
            {
                "rank": 0,
                "gap_id": gap.get("gap_id"),
                "description": gap.get("description") or gap.get("gap_description") or "",
                "gap_description": gap.get("description") or gap.get("gap_description") or "",
                "gap_type": gap.get("gap_type"),
                "gap_track": priority["track"],
                "gap_candidate_pool": candidate_pool,
                "eligible_for_hypothesis_generation": eligible_for_hypothesis,
                "mechanistic_priority": priority["mechanistic_priority"],
                "mechanistic_priority_breakdown": priority,
                "exploration_value_score": priority["mechanistic_priority"],
                "raw_exploration_value_score": legacy_score,
                "importance": importance_label(priority["mechanistic_priority"]),
                "tractability": gap.get("feasibility", "medium"),
                "strategic_alignment": alignment,
                "supporting_references": refs[:5],
                "recommended_approach": gap.get("suggested_research_path") or "Design a focused validation study with explicit baselines and failure criteria.",
                "ranking_reason": priority["reason"] + " " + relevance["reason"] + f" Legacy comparison score: {legacy_score}; {legacy_reason}" + parent_priority_reason,
                "mechanism_relevance": relevance,
                "parent_subhypothesis_priority": parent_priority,
                "parent_subhypothesis_priority_overall": float(parent_priority.get("overall") or 0.0),
            }
        )
        # Role is persisted with the ranked TanXi gap itself.  Downstream
        # stages therefore receive a scientific-role declaration from the
        # moment the gap enters project state, rather than reclassifying an
        # anonymous ranked list only at MingLi time.
        role_detail = classify_gap_analysis_role(project, item)
        item["analysis_role"] = role_detail["analysis_role"]
        item["analysis_role_detail"] = role_detail
        ranked.append(item)
    ranked.sort(key=_tanxi_rank_sort_key)
    for index, item in enumerate(ranked[:max_gaps], 1):
        item["rank"] = index
    return ranked[:max_gaps]

def gaps_from_density_holes(project: dict[str, Any], holes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for hole in holes[:12]:
        refs = [ref for ref in hole.get("supporting_references", []) if ref]
        if not refs:
            continue
        if hole.get("current_evidence_level") == "none":
            description = f"Density hole: '{hole.get('method')}' has no recorded validation in '{hole.get('scenario')}'."
            gap_type = "combinatorial"
        else:
            missing = ", ".join(hole.get("missing_benchmarks", [])[:3])
            description = f"Density hole: '{hole.get('method')}' in '{hole.get('scenario')}' lacks benchmark coverage for {missing}."
            gap_type = "improvement"
        gaps.append(
            assess_gap_dict(
                project,
                make_gap(
                    gap_type=gap_type,
                    description=description,
                    supporting_references=refs,
                    suggested_research_path="Use the dense neighboring literature as controls, then test the sparse intersection with explicit benchmark coverage.",
                    value_argument=str(hole.get("why_important") or "The area is important but under-supported in the current evidence graph."),
                ),
            )
        )
    return gaps

def gaps_from_unconnected_pairs(
    project: dict[str, Any],
    pairs: list[dict[str, Any]],
    rejected_audits: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for pair in pairs[:8]:
        refs = [ref for ref in pair.get("supporting_references", []) if ref]
        if len(refs) < 2:
            continue
        gate = semantic_plausibility_for_pair(project, str(pair.get("concept_a") or ""), str(pair.get("concept_b") or ""))
        try:
            from ._literature_scoring import fields_are_incompatible
        except ImportError:
            from _literature_scoring import fields_are_incompatible
        declared_field_a = str(pair.get("field_a") or "")
        declared_field_b = str(pair.get("field_b") or "")
        if (
            declared_field_a
            and declared_field_b
            and fields_are_incompatible(declared_field_a, declared_field_b)
            and not gate.get("bridge_terms")
        ):
            gate = dict(gate)
            gate.update({
                "verdict": "REJECT",
                "cross_domain_distance": 1.0,
                "cross_domain_risk": "HIGH",
                "declared_field_pair": [declared_field_a, declared_field_b],
                "reason": (
                    str(gate.get("reason") or "")
                    + f"; declared source fields are incompatible without a scientific bridge: {declared_field_a} -> {declared_field_b}"
                ).strip("; "),
            })
        if gate.get("verdict") == "REJECT":
            if isinstance(rejected_audits, list):
                rejected_audits.append({
                    "artifact_type": "REJECTED_CROSS_DOMAIN_PAIR",
                    "candidate_type": "migration_or_unconnected_pair",
                    "concept_a": str(pair.get("concept_a") or ""),
                    "concept_b": str(pair.get("concept_b") or ""),
                    "field_a": str(pair.get("field_a") or ""),
                    "field_b": str(pair.get("field_b") or ""),
                    "supporting_references": refs[:8],
                    "semantic_plausibility": gate,
                    "verdict": "REJECT",
                    "reason": str(gate.get("reason") or "Cross-domain pair lacks a scientific bridge."),
                    "may_enter_socrates": False,
                    "may_enter_mingli": False,
                })
            continue
        gaps.append(
            assess_gap_dict(
                project,
                make_gap(
                    gap_type="migration",
                    description=(
                        f"Cross-disciplinary unconnected pair: '{pair.get('concept_a')}' from {pair.get('field_a')} "
                        f"and '{pair.get('concept_b')}' from {pair.get('field_b')} have no recorded bridge in the current PaperGraph."
                    ),
                    supporting_references=refs,
                    suggested_research_path="Formulate a transfer hypothesis, audit incompatible assumptions, then run a minimal bridge experiment or benchmark.",
                    value_argument=str(pair.get("potential_synergy") or "The pair may expose transferable mechanisms across disciplinary boundaries."),
                ),
            )
        )
        gaps[-1]["semantic_plausibility"] = gate
    return gaps

def gaps_from_suspended_problems(project: dict[str, Any], problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for problem in problems[:8]:
        refs = [ref for ref in problem.get("supporting_references", []) if ref]
        branch = normalized_subhypothesis_id(problem.get("sub_hypothesis_id"))
        source_units = [
            dict(unit)
            for unit in (problem.get("source_evidence_units") or [])
            if isinstance(unit, dict)
            and str(unit.get("paper_id") or "").strip()
            and str(unit.get("source_unit_id") or "").strip()
        ]
        # Never create a bare secondary "problem" candidate.  The source
        # detector must carry a concrete SH and paper/source-unit provenance;
        # otherwise a generic literature fragment gets presented as a project
        # research opportunity with SH=(missing).
        if not refs or not branch or not source_units:
            continue
        gap = make_gap(
            gap_type="problem",
            description=f"Suspended problem: {problem.get('problem')}",
            supporting_references=refs,
            suggested_research_path="Verify whether the source cue denotes a concrete unresolved scientific question, then trace the barrier to a testable method, dataset, or model comparison.",
            value_argument=(
                "The source contains a suspended-problem cue that requires "
                f"source-bound verification before it can be treated as unresolved; "
                f"reported barrier: {problem.get('barrier_to_progress')}."
            ),
        )
        gap["sub_hypothesis_id"] = branch
        gap["source_evidence_units"] = source_units
        gap["source_candidate_provenance"] = {
            **(
                dict(problem.get("source_candidate_provenance") or {})
                if isinstance(problem.get("source_candidate_provenance"), dict)
                else {}
            ),
            "sub_hypothesis_id": branch,
            "source": "suspended_problem_detector",
            "paper_ids": [str(unit.get("paper_id") or "") for unit in source_units],
            "source_unit_ids": [str(unit.get("source_unit_id") or "") for unit in source_units],
            "provenance_complete": True,
        }
        gaps.append(assess_gap_dict(project, gap))
    return gaps

def tanxi_importance_score(
    method: str,
    scenario: str,
    target_domain: str,
    method_support: dict[str, int],
    scenario_support: dict[str, int],
) -> int:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    score = 3
    score += min(3, method_support.get(method, 0))
    score += min(3, scenario_support.get(scenario, 0))
    target_terms = set(query_terms(target_domain))
    if target_terms and (target_terms & set(query_terms(f"{method} {scenario}"))):
        score += 2
    if any(term in f"{method} {scenario}".lower() for term in ("safety", "efficiency", "robust", "scalable", "uncertainty", "stability")):
        score += 1
    return max(1, min(10, score))

def record_field(record: dict[str, Any]) -> str:
    try:
        from ._literature_scoring import infer_research_field
    except ImportError:
        from _literature_scoring import infer_research_field
    field_name = str(record.get("field") or "").strip()
    if field_name:
        return field_name
    return infer_research_field(record)

def concepts_are_connected(project: dict[str, Any], left: str, right: str) -> bool:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_label
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import normalize_label
    left_norm = normalize_label(left)
    right_norm = normalize_label(right)
    for record in project_records_for_mapping(project):
        values = {
            normalize_label(record.get("method", "")),
            normalize_label(record.get("scenario", "")),
            normalize_label(record.get("benchmark", "")),
        }
        if left_norm in values and right_norm in values:
            return True
    return False

def concept_bridge_exists(project: dict[str, Any], left: str, right: str) -> bool:
    try:
        from ._literature_import import authoritative_descriptor_source_text
        from ._literature_search import query_terms
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_label
    except ImportError:
        from _literature_import import authoritative_descriptor_source_text
        from _literature_search import query_terms
        from _pipeline import project_records_for_mapping
        from _utils import normalize_label
    left_terms = set(query_terms(left))
    right_terms = set(query_terms(right))
    if not left_terms or not right_terms:
        return False
    records, _ = admitted_method_scenario_benchmark_records(
        project_records_for_mapping(project),
        allow_noncore_context=True,
    )
    for record in records:
        source_text = authoritative_descriptor_source_text(record)
        terms = set(query_terms(source_text))
        left_hit = bool(left_terms & terms) or normalize_label(left).lower() in source_text.lower()
        right_hit = bool(right_terms & terms) or normalize_label(right).lower() in source_text.lower()
        if left_hit and right_hit:
            return True
    return False

def cross_field_synergy(concept_a: str, concept_b: str, target_domain: str) -> str:
    target = f" for {target_domain}" if target_domain else ""
    return (
        f"Testing whether {concept_a} can constrain, evaluate, or operationalize {concept_b}{target} "
        "may reveal a non-obvious transfer path or boundary condition."
    )

def infer_barrier_to_progress(text: str) -> str:
    if any(term in text for term in ("data", "dataset", "measurement", "sample")):
        return "data or measurement bottleneck"
    if any(term in text for term in ("mechanism", "unclear", "unknown", "understand")):
        return "mechanistic uncertainty"
    if any(term in text for term in ("scale", "large-scale", "computational", "expensive")):
        return "scale or computational constraint"
    if any(term in text for term in ("robust", "stability", "failure", "degradation")):
        return "robustness or stability barrier"
    return "unspecified conceptual or technical barrier"

def align_gap_with_strategic_needs(gap: dict[str, Any], strategic_domains: list[str]) -> list[dict[str, Any]]:
    text = " ".join(str(gap.get(key, "")) for key in ("description", "value_argument", "suggested_research_path")).lower()
    alignments: list[dict[str, Any]] = []
    for domain in strategic_domains:
        keywords = strategic_need_keywords(domain)
        matched = [keyword for keyword in keywords if keyword in text]
        if matched:
            alignments.append(
                {
                    "strategic_domain": domain,
                    "matched_keywords": matched[:8],
                    "alignment_score": min(10, 4 + 2 * len(matched)),
                }
            )
    return alignments

def strategic_need_keywords(domain: str) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space
    normalized = normalize_space(domain).lower()
    table = {
        "carbon neutrality": ["carbon", "emission", "energy", "efficiency", "renewable", "storage", "catalyst"],
        "health": ["health", "clinical", "disease", "patient", "therapy", "diagnosis", "safety"],
        "energy": ["energy", "battery", "power", "grid", "catalyst", "hydrogen", "efficiency"],
        "food security": ["food", "crop", "agriculture", "yield", "soil", "resilience"],
        "ai for science": ["ai", "agent", "model", "automation", "scientific discovery", "workflow"],
        "advanced manufacturing": ["manufacturing", "robot", "automation", "process", "quality", "throughput"],
        "environment": ["environment", "climate", "ecosystem", "pollution", "water", "resilience"],
    }
    for key, keywords in table.items():
        if key in normalized or normalized in key:
            return keywords
    return query_terms(normalized)

def default_strategic_domains(project: dict[str, Any]) -> list[str]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(" ".join(str(project.get(key, "")) for key in ("domain", "title", "objective"))).lower()
    defaults = ["ai for science", "energy", "health", "carbon neutrality", "food security", "environment"]
    matched = [domain for domain in defaults if any(keyword in text for keyword in strategic_need_keywords(domain))]
    return matched or defaults[:3]

def tanxi_gap_priority_score(
    project: dict[str, Any],
    gap: dict[str, Any],
    alignment: list[dict[str, Any]],
    density_lookup: dict[str, dict[str, Any]],
) -> tuple[int, str]:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    novelty = int(gap.get("novelty_score") or 5)
    refs = len([ref for ref in gap.get("supporting_references", []) if ref])
    feasibility = str(gap.get("feasibility", "medium"))
    application = str(gap.get("application_value", "medium"))
    gap_type = str(gap.get("gap_type", ""))
    score = novelty
    score += min(2, refs)
    score += {"high": 2, "medium": 1, "low": -1}.get(application, 0)
    score += {"high": 2, "medium": 1, "low": -2}.get(feasibility, 0)
    if gap_type in {"migration", "problem", "mechanism_problem", "contradiction", "anomaly", "structural"}:
        score += 1
    if gap_type in {"mechanism_problem", "contradiction", "anomaly"}:
        score += 1
    if gap.get("mechanism_issue_signal") or gap.get("gap_signal"):
        score += 1
    if alignment:
        score += min(2, max(int(item.get("alignment_score", 0)) for item in alignment) // 4)
    description = str(gap.get("description", "")).lower()
    density_bonus = 0
    for topic, hole in density_lookup.items():
        if topic and any(term in description for term in query_terms(topic)):
            density_bonus = max(density_bonus, int(hole.get("importance_score") or 0) // 4)
    score += min(2, density_bonus)
    score = max(1, min(10, score))
    reason = (
        f"novelty={novelty}, refs={refs}, application={application}, feasibility={feasibility}, "
        f"type={gap_type}, strategic_matches={len(alignment)}, density_bonus={density_bonus}"
    )
    return score, reason

def importance_label(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"

def evolve_domain_subspaces(
    project_id: str,
    subspace_map_id: str = "",
    max_actions: int = 10,
) -> str:
    try:
        from ._literature_scoring import slug_label
        from ._pipeline import project_records_for_mapping
        from ._project import load_project, load_subspace_map, save_project, save_subspace_map
        from ._utils import clamp_int, new_id
    except ImportError:
        from _literature_scoring import slug_label
        from _pipeline import project_records_for_mapping
        from _project import load_project, load_subspace_map, save_project, save_subspace_map
        from _utils import clamp_int, new_id
    project = load_project(project_id)
    subspace_map = load_subspace_map(subspace_map_id) if subspace_map_id else synthesize_subspace_map_from_project(project)
    subspaces = [item for item in subspace_map.get("subspaces", []) if isinstance(item, dict)]
    records = project_records_for_mapping(project)
    metrics: list[dict[str, Any]] = []
    matched_by_subspace: dict[str, list[dict[str, Any]]] = {}
    for subspace in subspaces:
        sid = str(subspace.get("subspace_id") or slug_label(str(subspace.get("name") or "")) or new_id("subspace_item"))
        matched = records_matching_subspace(records, subspace)
        matched_by_subspace[sid] = matched
        metrics.append(subspace_state_metrics(subspace, matched, records))

    fission = detect_subspace_fission_signals(subspaces, matched_by_subspace)
    fusion = detect_subspace_fusion_signals(subspaces, matched_by_subspace)
    decline = detect_subspace_decline_signals(subspace_map, metrics)
    emergent = detect_emergent_subspaces(project, subspaces, records)
    proposed_actions = (fission + fusion + decline + emergent)[: clamp_int(max_actions, 1, 50)]
    report = {
        "subspace_evolution_id": new_id("subevo"),
        "project_id": project_id,
        "subspace_map_id": subspace_map.get("subspace_map_id", ""),
        "createdAt": time.time(),
        "summary": {
            "subspaces": len(subspaces),
            "records_scanned": len(records),
            "actions": len(proposed_actions),
            "maturity_counts": dict(Counter(str(item.get("maturity")) for item in metrics)),
        },
        "metrics": metrics,
        "signals": {
            "fission": fission,
            "fusion": fusion,
            "decline": decline,
            "emergent": emergent,
        },
        "proposed_actions": proposed_actions,
        "next_step": "Review proposed_actions. Use selected/fission/fusion/emergent subspaces as focus_branches before MingLi hypothesis evolution.",
    }
    subspace_map.setdefault("evolution_history", []).append(report)
    subspace_map["latest_evolution"] = report
    if subspace_map.get("subspace_map_id"):
        save_subspace_map(subspace_map)
    project.setdefault("subspace_evolution_reports", []).append(report)
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "subspace_evolution", project_id=project_id, actions=len(proposed_actions))
    return json.dumps(report, ensure_ascii=False, indent=2)

def synthesize_subspace_map_from_project(project: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._pipeline import project_records_for_mapping
        from ._project import normalize_domain_subspace
        from ._utils import is_unknown_value, normalize_label
    except ImportError:
        from _literature_search import query_terms
        from _pipeline import project_records_for_mapping
        from _project import normalize_domain_subspace
        from _utils import is_unknown_value, normalize_label
    knowledge_map = project.get("knowledge_map", {}) if isinstance(project.get("knowledge_map"), dict) else {}
    scenarios = list(knowledge_map.get("main_scenarios") or [])
    if not scenarios:
        scenarios = sorted({normalize_label(record.get("scenario", "")) for record in project_records_for_mapping(project)})
    subspaces = [
        normalize_domain_subspace(
            {
                "name": scenario,
                "keywords": query_terms(scenario),
                "description": "Synthetic subspace derived from current PaperGraph scenario coverage.",
                "generated_by": "project_synthesis",
            },
            domain=str(project.get("domain", "")),
        )
        for scenario in scenarios
        if scenario and not is_unknown_value(scenario)
    ]
    if not subspaces:
        subspaces = [
            normalize_domain_subspace(
                {
                    "name": str(project.get("domain") or "current project"),
                    "keywords": query_terms(str(project.get("domain") or project.get("title") or "")),
                    "generated_by": "project_synthesis",
                },
                domain=str(project.get("domain", "")),
            )
        ]
    return {
        "subspace_map_id": "",
        "domain": project.get("domain", ""),
        "generated_by": "project_synthesis",
        "subspaces": subspaces,
        "probe_results": [],
    }

def records_matching_subspace(records: list[dict[str, Any]], subspace: dict[str, Any]) -> list[dict[str, Any]]:
    terms = subspace_terms(subspace)
    if not terms:
        return []
    matched: list[dict[str, Any]] = []
    for record in records:
        text = record_search_text(record)
        if any(term in text for term in terms):
            matched.append(record)
    return matched

def subspace_terms(subspace: dict[str, Any]) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import string_list, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import string_list, unique_preserve_order
    raw: list[str] = []
    raw.extend(query_terms(str(subspace.get("name") or "")))
    raw.extend(query_terms(" ".join(string_list(subspace.get("aliases")))))
    raw.extend(query_terms(" ".join(string_list(subspace.get("keywords")))))
    return unique_preserve_order([term.lower() for term in raw if len(term) >= 3])[:24]

def record_search_text(record: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space, scalar
    except ImportError:
        from _utils import normalize_space, scalar
    return normalize_space(
        " ".join(
            scalar(record.get(key))
            for key in (
                "title",
                "abstract",
                "conclusion",
                "method",
                "scenario",
                "benchmark",
                "contribution",
                "limitation",
                "citation",
            )
        )
    ).lower()

def subspace_state_metrics(subspace: dict[str, Any], matched: list[dict[str, Any]], all_records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from ._utils import extract_year, is_unknown_value, normalize_label, numeric_value
    except ImportError:
        from _utils import extract_year, is_unknown_value, normalize_label, numeric_value
    current_year = time.localtime().tm_year
    years = [int(year) for year in (extract_year(str(record.get("year") or record.get("citation") or "")) for record in matched) if year]
    recent_count = sum(1 for year in years if year >= current_year - 1)
    older_count = max(0, len(years) - recent_count)
    citations = [numeric_value(record.get("citation_count")) for record in matched]
    high_impact = sum(1 for value in citations if value >= 100)
    methods = {normalize_label(record.get("method", "")) for record in matched if not is_unknown_value(record.get("method", ""))}
    matched_citations = {record_identity(record) for record in matched if record_identity(record)}
    cross_connections = 0
    for record in all_records:
        identity = record_identity(record)
        if identity not in matched_citations:
            continue
        labels = [normalize_label(record.get(key, "")) for key in ("method", "scenario", "benchmark")]
        if len([label for label in labels if label and not is_unknown_value(label)]) >= 3:
            cross_connections += 1
    growth_rate = round((recent_count - older_count / max(1, max(1, len(set(years)) - 1))) / 12.0, 3)
    if len(matched) <= 1 and recent_count > 0:
        maturity = "emerging"
    elif growth_rate > 0.15:
        maturity = "growing"
    elif len(matched) >= 5 and recent_count == 0:
        maturity = "declining"
    elif len(matched) >= 4:
        maturity = "mature"
    else:
        maturity = "emerging" if recent_count else "unknown"
    return {
        "subspace_id": subspace.get("subspace_id"),
        "name": subspace.get("name"),
        "paper_count_total": len(matched),
        "paper_count_recent_24m": recent_count,
        "growth_delta_per_month": growth_rate,
        "high_impact_ratio": round(high_impact / max(1, len(matched)), 3),
        "method_diversity": len(methods),
        "cross_connection_count": cross_connections,
        "maturity": maturity,
        "top_methods": sorted(methods)[:8],
        "top_terms": top_record_terms(matched, limit=10),
    }

def detect_subspace_fission_signals(
    subspaces: list[dict[str, Any]],
    matched_by_subspace: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for subspace in subspaces:
        sid = str(subspace.get("subspace_id") or "")
        matched = matched_by_subspace.get(sid, [])
        candidate_terms = top_record_terms(matched, limit=8)
        if len(candidate_terms) < 4 or len(matched) < 3:
            continue
        cluster_a = candidate_terms[0::2][:4]
        cluster_b = candidate_terms[1::2][:4]
        overlap = set(cluster_a) & set(cluster_b)
        if len(cluster_a) >= 2 and len(cluster_b) >= 2 and not overlap:
            signals.append(
                {
                    "action": "fission",
                    "subspace_id": sid,
                    "subspace": subspace.get("name"),
                    "reason": "Internal records show at least two separable keyword clusters.",
                    "suggested_children": [
                        {
                            "name": f"{subspace.get('name')} / {' '.join(cluster_a[:2])}",
                            "keywords": cluster_a,
                        },
                        {
                            "name": f"{subspace.get('name')} / {' '.join(cluster_b[:2])}",
                            "keywords": cluster_b,
                        },
                    ],
                }
            )
    return signals

def detect_subspace_fusion_signals(
    subspaces: list[dict[str, Any]],
    matched_by_subspace: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for index, left in enumerate(subspaces):
        left_id = str(left.get("subspace_id") or "")
        left_records = {record_identity(record) for record in matched_by_subspace.get(left_id, []) if record_identity(record)}
        left_terms = set(subspace_terms(left))
        for right in subspaces[index + 1 :]:
            right_id = str(right.get("subspace_id") or "")
            right_records = {record_identity(record) for record in matched_by_subspace.get(right_id, []) if record_identity(record)}
            right_terms = set(subspace_terms(right))
            record_jaccard = jaccard_score(left_records, right_records)
            term_jaccard = jaccard_score(left_terms, right_terms)
            if record_jaccard >= 0.3 or (record_jaccard >= 0.15 and term_jaccard >= 0.25):
                signals.append(
                    {
                        "action": "fusion",
                        "subspace_ids": [left_id, right_id],
                        "subspaces": [left.get("name"), right.get("name")],
                        "record_overlap": round(record_jaccard, 3),
                        "keyword_overlap": round(term_jaccard, 3),
                        "suggested_name": f"{left.get('name')} + {right.get('name')}",
                        "reason": "The two subspaces share enough papers or retrieval vocabulary to risk redundant treatment.",
                    }
                )
    return signals

def detect_subspace_decline_signals(subspace_map: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_reports = subspace_map.get("evolution_history", [])
    previous_metrics: dict[str, dict[str, Any]] = {}
    if previous_reports:
        latest = previous_reports[-1]
        for item in latest.get("metrics", []):
            if isinstance(item, dict) and item.get("subspace_id"):
                previous_metrics[str(item["subspace_id"])] = item
    signals: list[dict[str, Any]] = []
    for item in metrics:
        sid = str(item.get("subspace_id") or "")
        prev = previous_metrics.get(sid)
        declined = bool(prev and int(item.get("paper_count_recent_24m") or 0) < int(prev.get("paper_count_recent_24m") or 0))
        if item.get("maturity") == "declining" or declined:
            signals.append(
                {
                    "action": "archive_or_deprioritize",
                    "subspace_id": sid,
                    "subspace": item.get("name"),
                    "reason": "Recent paper support is low or declining relative to the previous scan.",
                    "maturity": item.get("maturity"),
                }
            )
    return signals

def detect_emergent_subspaces(project: dict[str, Any], subspaces: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered_terms = set()
    for subspace in subspaces:
        covered_terms.update(subspace_terms(subspace))
    candidates = [term for term in top_record_terms(records, limit=18) if term not in covered_terms]
    if len(candidates) < 3:
        return []
    return [
        {
            "action": "new_subspace",
            "subspace": " / ".join(candidates[:3]),
            "keywords": candidates[:8],
            "reason": "Frequent project terms are not represented in the current subspace map.",
            "suggested_parent": project.get("domain", ""),
        }
    ]

def top_record_terms(records: list[dict[str, Any]], limit: int = 10) -> list[str]:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    stop = {
        "study",
        "paper",
        "method",
        "scenario",
        "benchmark",
        "using",
        "based",
        "analysis",
        "model",
        "models",
        "result",
        "results",
        "effect",
        "effects",
        "system",
    }
    counter: Counter[str] = Counter()
    for record in records:
        for term in query_terms(record_search_text(record)):
            if term not in stop and len(term) >= 4:
                counter[term] += 1
    return [term for term, _ in counter.most_common(limit)]

def record_identity(record: dict[str, Any]) -> str:
    try:
        from ._utils import first_nonempty
    except ImportError:
        from _utils import first_nonempty
    return first_nonempty(
        [
            str(record.get("paper_id") or ""),
            str(record.get("citation") or ""),
            str(record.get("title") or ""),
            str(record.get("evidence_id") or ""),
        ]
    )

def jaccard_score(left: set[Any], right: set[Any]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))

def build_temporal_knowledge_graph(project_id: str) -> str:
    try:
        from ._pipeline import project_records_for_mapping
        from ._project import load_project, save_project
        from ._utils import extract_year, is_unknown_value, new_id, normalize_label, numeric_value
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _project import load_project, save_project
        from _utils import extract_year, is_unknown_value, new_id, normalize_label, numeric_value
    project = load_project(project_id)
    records = project_records_for_mapping(project)
    triples: list[dict[str, Any]] = []
    for record in records:
        method = normalize_label(record.get("method", ""))
        scenario = normalize_label(record.get("scenario", ""))
        alignment_assessment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        branch = normalized_subhypothesis_id(
            record.get("retrieval_branch")
            or record.get("sub_hypothesis_id")
            or alignment_assessment.get("sub_hypothesis_id")
        )
        benchmark = normalize_label(record.get("benchmark", ""))
        if any(is_unknown_value(value) for value in (method, scenario, benchmark)):
            continue
        year = extract_year(str(record.get("year") or record.get("citation") or ""))
        triples.append(
            {
                "method": method,
                "scenario": scenario,
                "benchmark": benchmark,
                "year": int(year) if year else None,
                "citation_count": int(numeric_value(record.get("citation_count"))),
                "reference": record_identity(record),
            }
        )
    yearly_counts = temporal_yearly_counts(triples)
    method_lifecycles = {
        method: temporal_lifecycle([item for item in triples if item["method"] == method])
        for method in sorted({item["method"] for item in triples})
    }
    scenario_lifecycles = {
        scenario: temporal_lifecycle([item for item in triples if item["scenario"] == scenario])
        for scenario in sorted({item["scenario"] for item in triples})
    }
    hotspot_predictions = predict_temporal_hotspots(method_lifecycles, scenario_lifecycles)
    report = {
        "temporal_kg_id": new_id("tkg"),
        "project_id": project_id,
        "createdAt": time.time(),
        "triple_count": len(triples),
        "triples": triples,
        "yearly_counts": yearly_counts,
        "method_lifecycles": method_lifecycles,
        "scenario_lifecycles": scenario_lifecycles,
        "hotspot_predictions": hotspot_predictions,
        "next_step": "Use hotspot_predictions as emerging constraints for structural gap detection and MingLi hypothesis generation.",
    }
    project["temporal_knowledge_graph"] = report
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "temporal_kg_built", project_id=project_id, triples=len(triples))
    return json.dumps(report, ensure_ascii=False, indent=2)

def temporal_yearly_counts(triples: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in triples:
        if item.get("year"):
            counts[str(item["year"])] += 1
    return dict(sorted(counts.items()))

def temporal_lifecycle(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = temporal_yearly_counts(items)
    if not counts:
        return {"status": "unknown", "yearly_counts": {}, "growth_rate": 0.0, "peak_year": ""}
    years = sorted(int(year) for year in counts)
    peak_year = max(counts, key=counts.get)
    if len(years) == 1:
        growth = float(counts[str(years[0])])
    else:
        first = counts[str(years[0])]
        last = counts[str(years[-1])]
        growth = round((last - first) / max(1, years[-1] - years[0]), 3)
    recent_year = max(years)
    recent = counts[str(recent_year)]
    prior = sum(count for year, count in counts.items() if int(year) < recent_year) / max(1, len(counts) - 1)
    if recent >= prior * 1.5 and recent >= 2:
        status = "growing"
    elif recent < prior * 0.5 and prior >= 2:
        status = "declining"
    elif sum(counts.values()) >= 5:
        status = "mature"
    else:
        status = "emerging"
    return {
        "status": status,
        "yearly_counts": counts,
        "growth_rate": growth,
        "peak_year": peak_year,
        "total": sum(counts.values()),
    }

def predict_temporal_hotspots(
    method_lifecycles: dict[str, dict[str, Any]],
    scenario_lifecycles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for kind, lifecycles in (("method", method_lifecycles), ("scenario", scenario_lifecycles)):
        for name, lifecycle in lifecycles.items():
            score = 0.0
            if lifecycle.get("status") in {"growing", "emerging"}:
                score += 2.0
            score += min(3.0, max(0.0, float(lifecycle.get("growth_rate") or 0.0)))
            score += min(2.0, float(lifecycle.get("total") or 0.0) / 3.0)
            if score > 0:
                candidates.append(
                    {
                        "concept": name,
                        "concept_type": kind,
                        "forecast": "likely_hotspot" if score >= 3 else "watchlist",
                        "hotspot_score": round(score, 3),
                        "lifecycle": lifecycle,
                    }
                )
    candidates.sort(key=lambda item: (-float(item["hotspot_score"]), item["concept"]))
    return candidates[:12]

def detect_structural_knowledge_gaps(project_id: str, max_gaps: int = 10) -> str:
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    project = load_project(project_id)
    if not project.get("knowledge_map"):
        build_knowledge_map(project_id)
        project = load_project(project_id)
    graph = build_concept_graph(project)
    structural_items = structural_gap_items(project, graph, max_gaps=max_gaps * 2)
    gaps = [
        assess_gap_dict(
            project,
            make_gap(
                gap_type="structural",
                description=item["description"],
                supporting_references=item.get("supporting_references", []),
                suggested_research_path=item.get("recommended_action", "Design a bridge study that connects the sparse graph region with explicit evidence."),
                value_argument=item.get("value_argument", "Knowledge graph topology suggests this gap may affect field-level integration."),
            ),
        )
        for item in structural_items
    ]
    for gap, item in zip(gaps, structural_items):
        gap["structural_gap"] = item
    gaps = dedupe_knowledge_gaps(gaps)[:max_gaps]
    project["structural_gap_analysis"] = {
        "graph_summary": {
            "node_count": len(graph["nodes"]),
            "edge_count": sum(len(value) for value in graph["adjacency"].values()) // 2,
            "components": len(connected_components(graph["adjacency"])),
        },
        "items": structural_items,
        "gaps": gaps,
    }
    project.setdefault("knowledge_gaps", [])
    existing_ids = {gap.get("gap_id") for gap in project["knowledge_gaps"]}
    for gap in gaps:
        if gap.get("gap_id") not in existing_ids:
            project["knowledge_gaps"].append(gap)
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "structural_gaps_detected", project_id=project_id, count=len(gaps))
    return json.dumps(project["structural_gap_analysis"], ensure_ascii=False, indent=2)

def build_concept_graph(project: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import is_unknown_value, normalize_label
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import is_unknown_value, normalize_label
    nodes: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, set[str]] = defaultdict(set)
    edge_refs: dict[tuple[str, str], list[str]] = defaultdict(list)
    records, _ = admitted_method_scenario_benchmark_records(
        project_records_for_mapping(project),
        allow_noncore_context=True,
    )
    for record in records:
        labels = {
            "method": normalize_label(record.get("method", "")),
            "scenario": normalize_label(record.get("scenario", "")),
            "benchmark": normalize_label(record.get("benchmark", "")),
        }
        labels = {kind: label for kind, label in labels.items() if label and not is_unknown_value(label)}
        reference = record_identity(record)
        for kind, label in labels.items():
            node_id = f"{kind}:{label}"
            nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label, "references": []})
            if reference and reference not in nodes[node_id]["references"]:
                nodes[node_id]["references"].append(reference)
        label_items = list(labels.items())
        for left_index, (left_kind, left_label) in enumerate(label_items):
            for right_kind, right_label in label_items[left_index + 1 :]:
                left_id = f"{left_kind}:{left_label}"
                right_id = f"{right_kind}:{right_label}"
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)
                key = tuple(sorted((left_id, right_id)))
                if reference and reference not in edge_refs[key]:
                    edge_refs[key].append(reference)
    for node_id in nodes:
        adjacency.setdefault(node_id, set())
    return {"nodes": nodes, "adjacency": adjacency, "edge_refs": edge_refs}

def structural_gap_items(project: dict[str, Any], graph: dict[str, Any], max_gaps: int) -> list[dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = graph["nodes"]
    adjacency: dict[str, set[str]] = graph["adjacency"]
    degrees = {node_id: len(neighbors) for node_id, neighbors in adjacency.items()}
    avg_degree = sum(degrees.values()) / max(1, len(degrees))
    items: list[dict[str, Any]] = []
    for node_id, degree in sorted(degrees.items(), key=lambda pair: (pair[1], pair[0])):
        node = nodes.get(node_id, {"label": node_id, "kind": "concept", "references": []})
        if degree == 0:
            gap_type = "isolated_node"
            severity = "high"
        elif degree < max(1.0, avg_degree * 0.45):
            gap_type = "low_degree_node"
            severity = "medium"
        else:
            continue
        items.append(
            {
                "type": gap_type,
                "severity": severity,
                "node": node.get("label"),
                "node_kind": node.get("kind"),
                "degree": degree,
                "average_degree": round(avg_degree, 3),
                "description": f"Structural gap: {node.get('kind')} '{node.get('label')}' is weakly connected in the PaperGraph concept topology.",
                "recommended_action": "Search for bridge papers or design a validation study linking this concept to dense neighboring methods, scenarios, or benchmarks.",
                "value_argument": "Weakly connected concepts can indicate neglected mechanisms, under-benchmarked scenarios, or missing translational bridges.",
                "supporting_references": node.get("references", [])[:5],
            }
        )
    items.extend(detect_bottleneck_gap_items(graph, max_items=max_gaps))
    items.extend(detect_missing_bridge_items(project, graph, max_items=max_gaps))
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (severity_rank.get(str(item.get("severity")), 9), item.get("type", ""), item.get("description", "")))
    return items[:max_gaps]

def detect_bottleneck_gap_items(graph: dict[str, Any], max_items: int = 10) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = graph["adjacency"]
    nodes: dict[str, dict[str, Any]] = graph["nodes"]
    base_components = len(connected_components(adjacency))
    items: list[dict[str, Any]] = []
    for node_id, neighbors in adjacency.items():
        if len(neighbors) < 2:
            continue
        reduced = {node: set(values) - {node_id} for node, values in adjacency.items() if node != node_id}
        component_count = len(connected_components(reduced))
        if component_count > base_components:
            node = nodes.get(node_id, {"label": node_id, "kind": "concept", "references": []})
            items.append(
                {
                    "type": "bottleneck_node",
                    "severity": "medium",
                    "node": node.get("label"),
                    "node_kind": node.get("kind"),
                    "degree": len(neighbors),
                    "description": f"Structural gap: {node.get('kind')} '{node.get('label')}' is a bottleneck connecting otherwise separated knowledge regions.",
                    "recommended_action": "Create redundant bridge evidence around this bottleneck so the field does not depend on a single concept path.",
                    "value_argument": "Bottleneck concepts reveal fragile knowledge integration and are strong candidates for mechanism clarification.",
                    "supporting_references": node.get("references", [])[:5],
                }
            )
    return items[:max_items]

def detect_missing_bridge_items(project: dict[str, Any], graph: dict[str, Any], max_items: int = 10) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import is_unknown_value, normalize_label
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import is_unknown_value, normalize_label
    records, _ = admitted_method_scenario_benchmark_records(
        project_records_for_mapping(project),
        allow_noncore_context=True,
    )
    field_to_nodes: dict[str, set[str]] = defaultdict(set)
    for record in records:
        field_name = record_field(record)
        for kind in ("method", "scenario", "benchmark"):
            label = normalize_label(record.get(kind, ""))
            if label and not is_unknown_value(label):
                field_to_nodes[field_name].add(f"{kind}:{label}")
    fields = [field for field, nodes in field_to_nodes.items() if len(nodes) >= 2]
    items: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = graph["adjacency"]
    for index, left in enumerate(fields):
        for right in fields[index + 1 :]:
            left_nodes = field_to_nodes[left]
            right_nodes = field_to_nodes[right]
            bridge_edges = sum(1 for node in left_nodes for neighbor in adjacency.get(node, set()) if neighbor in right_nodes)
            if bridge_edges == 0:
                refs = references_for_field_pair(records, left, right)
                items.append(
                    {
                        "type": "missing_community_bridge",
                        "severity": "high",
                        "community_a": left,
                        "community_b": right,
                        "description": f"Structural gap: communities '{left}' and '{right}' have no concept bridge in the current PaperGraph.",
                        "recommended_action": "Look for transfer papers or design a cross-field experiment that connects one method from the source community to one scenario in the target community.",
                        "value_argument": "Disconnected communities can hide high-value cross-domain transfer opportunities.",
                        "supporting_references": refs[:6],
                    }
                )
    return items[:max_items]

def connected_components(adjacency: dict[str, set[str]]) -> list[set[str]]:
    unseen = set(adjacency)
    components: list[set[str]] = []
    while unseen:
        start = unseen.pop()
        stack = [start]
        component = {start}
        while stack:
            node = stack.pop()
            for neighbor in adjacency.get(node, set()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components

def references_for_field_pair(records: list[dict[str, Any]], left: str, right: str) -> list[str]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    refs: list[str] = []
    for record in records:
        if record_field(record) in {left, right}:
            identity = record_identity(record)
            if identity:
                refs.append(identity)
    return unique_preserve_order(refs)

def find_structural_analogy_transfers(
    project_id: str,
    target_scenario: str = "",
    threshold: float = 0.55,
    max_results: int = 10,
) -> str:
    try:
        from ._pipeline import project_records_for_mapping
        from ._project import load_project, save_project
        from ._utils import clamp_int, is_unknown_value, new_id, normalize_label, unique_preserve_order
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _project import load_project, save_project
        from _utils import clamp_int, is_unknown_value, new_id, normalize_label, unique_preserve_order
    project = load_project(project_id)
    records = project_records_for_mapping(project)
    scenario_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        scenario = normalize_label(record.get("scenario", ""))
        if scenario and not is_unknown_value(scenario):
            scenario_records[scenario].append(record)
    vectors = {scenario: encode_problem_structure(scenario, recs) for scenario, recs in scenario_records.items()}
    target = normalize_label(target_scenario)
    pairs: list[dict[str, Any]] = []
    scenarios = sorted(vectors)
    for index, left in enumerate(scenarios):
        if target and left != target:
            continue
        for right in scenarios:
            if left == right:
                continue
            similarity = problem_structure_similarity(vectors[left], vectors[right])
            if similarity < threshold:
                continue
            source_methods = methods_for_scenario(scenario_records[right])
            target_methods = methods_for_scenario(scenario_records[left])
            transferable = [method for method in source_methods if method not in target_methods]
            if not transferable:
                continue
            pairs.append(
                {
                    "target_scenario": left,
                    "analog_source_scenario": right,
                    "structural_similarity": round(similarity, 3),
                    "target_structure": vectors[left],
                    "source_structure": vectors[right],
                    "candidate_methods_to_transfer": transferable[:6],
                    "feasibility": analogy_feasibility(vectors[right], vectors[left]),
                    "supporting_references": unique_preserve_order(
                        [record_identity(record) for record in scenario_records[right][:3] + scenario_records[left][:3] if record_identity(record)]
                    ),
                    "hypothesis_hint": (
                        f"Because '{left}' and '{right}' share a similar problem structure, test whether "
                        f"{transferable[0]} can be adapted from '{right}' to '{left}'."
                    ),
                }
            )
        if target:
            break
    pairs.sort(key=lambda item: (-float(item["structural_similarity"]), item["target_scenario"], item["analog_source_scenario"]))
    report = {
        "analogy_report_id": new_id("analog"),
        "project_id": project_id,
        "target_scenario": target_scenario,
        "threshold": threshold,
        "scenario_count": len(scenarios),
        "analogy_transfers": pairs[: clamp_int(max_results, 1, 50)],
        "next_step": "Feed high-similarity transfers into MingLi as mutation/crossover material for hypothesis evolution.",
    }
    project.setdefault("structural_analogy_reports", []).append(report)
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "structural_analogies_found", project_id=project_id, count=len(report["analogy_transfers"]))
    return json.dumps(report, ensure_ascii=False, indent=2)

def encode_problem_structure(scenario: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(" ".join([scenario] + [record_search_text(record) for record in records])).lower()
    return {
        "problem_type": classify_problem_type(text),
        "data_type": classify_data_type(text),
        "constraint_type": classify_constraint_type(text),
        "scale": classify_problem_scale(text, len(records)),
        "objective": classify_objective_type(text),
    }

def classify_problem_type(text: str) -> str:
    if any(term in text for term in ("optimiz", "optimal", "scheduling", "design")):
        return "optimization"
    if any(term in text for term in ("classif", "diagnos", "detection", "screening")):
        return "classification"
    if any(term in text for term in ("generat", "synthesis", "design new", "de novo")):
        return "generation"
    if any(term in text for term in ("control", "policy", "intervention", "regulat")):
        return "control"
    return "prediction"

def classify_data_type(text: str) -> str:
    if any(term in text for term in ("graph", "network", "pathway", "interaction")):
        return "graph"
    if any(term in text for term in ("image", "imaging", "microscopy", "radiology")):
        return "image"
    if any(term in text for term in ("sequence", "time series", "temporal", "longitudinal")):
        return "sequence"
    if any(term in text for term in ("text", "language", "document", "literature")):
        return "text"
    if any(term in text for term in ("single-cell", "multi-omics", "genomics", "transcriptomics", "high-dimensional")):
        return "high_dimensional_tabular"
    return "tabular_or_mixed"

def classify_constraint_type(text: str) -> str:
    if any(term in text for term in ("safety", "ethical", "toxicity", "stability", "hard constraint")):
        return "hard_constraints"
    if any(term in text for term in ("cost", "limited", "trade-off", "resource", "sample")):
        return "soft_constraints"
    return "weak_or_unspecified_constraints"

def classify_problem_scale(text: str, record_count: int) -> str:
    if any(term in text for term in ("population", "large-scale", "atlas", "cohort", "foundation")) or record_count >= 8:
        return "large"
    if record_count >= 3:
        return "medium"
    return "small"

def classify_objective_type(text: str) -> str:
    if any(term in text for term in ("mechanism", "causal", "pathway", "explain")):
        return "mechanistic_explanation"
    if any(term in text for term in ("performance", "accuracy", "efficiency", "yield")):
        return "performance_improvement"
    if any(term in text for term in ("translation", "clinical", "deployment", "application")):
        return "translation"
    return "discovery"

def problem_structure_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    keys = ["problem_type", "data_type", "constraint_type", "scale", "objective"]
    matches = sum(1 for key in keys if left.get(key) == right.get(key))
    partial = 0.0
    if left.get("data_type") in {"high_dimensional_tabular", "tabular_or_mixed"} and right.get("data_type") in {"high_dimensional_tabular", "tabular_or_mixed"}:
        partial += 0.5
    if left.get("problem_type") in {"prediction", "classification"} and right.get("problem_type") in {"prediction", "classification"}:
        partial += 0.5
    return min(1.0, (matches + partial) / len(keys))

def methods_for_scenario(records: list[dict[str, Any]]) -> list[str]:
    try:
        from ._utils import is_unknown_value, normalize_label
    except ImportError:
        from _utils import is_unknown_value, normalize_label
    return sorted(
        {
            normalize_label(record.get("method", ""))
            for record in records
            if normalize_label(record.get("method", "")) and not is_unknown_value(record.get("method", ""))
        }
    )

def analogy_feasibility(source: dict[str, Any], target: dict[str, Any]) -> str:
    similarity = problem_structure_similarity(source, target)
    if similarity >= 0.8 and source.get("constraint_type") == target.get("constraint_type"):
        return "high"
    if similarity >= 0.6:
        return "medium"
    return "low"

def make_gap(
    gap_type: str,
    description: str,
    supporting_references: list[str],
    suggested_research_path: str,
    value_argument: str,
    hypothesis_ingredients: dict[str, Any] | None = None,
    counterfactual_leaves: list[str] | None = None,
    project_id: str = "",
) -> dict[str, Any]:
    try:
        from ._science_state import new_science_gap_id
        from ._utils import unique_preserve_order
    except ImportError:
        from _science_state import new_science_gap_id
        from _utils import unique_preserve_order
    default_ingredients = {
        "methods": [],
        "scenarios": [],
        "benchmarks": [],
        "measurement_resources": [],
        "numerical_bounds": [],
        "operating_conditions": [],
        "measurable_metrics": [],
    }
    if hypothesis_ingredients:
        for k, v in hypothesis_ingredients.items():
            if isinstance(v, list):
                default_ingredients[k] = v
            else:
                default_ingredients[k] = [v] if v else []
    return {
        "gap_id": new_science_gap_id(project_id),
        "project_id": str(project_id or ""),
        "gap_type": gap_type,
        "gap_candidate_pool": default_gap_candidate_pool(gap_type),
        "description": description,
        "supporting_references": unique_preserve_order([ref for ref in supporting_references if ref])[:8],
        "novelty_score": 5,
        "application_value": "medium",
        "feasibility": "medium",
        "suggested_research_path": suggested_research_path,
        "value_argument": value_argument,
        "status": "candidate",
        "createdAt": time.time(),
        "hypothesis_ingredients": default_ingredients,
        "counterfactual_leaves": counterfactual_leaves or [],
    }


def _source_bound_gap_report(project: dict[str, Any], *, limit: int) -> dict[str, Any]:
    """Reject a retired pre-V3 helper instead of dispatching into V3 TanXi."""

    del project, limit
    return {
        "schema_version": "retired_gap_detection_entrypoint_v3",
        "status": "REJECTED_INCOMPATIBLE_RETRIEVAL_ARTIFACT",
        "reason_code": "LEGACY_GAP_DETECTION_ENTRYPOINT_NOT_SUPPORTED",
        "candidates": [],
        "branch_states": [],
        "diagnostics": [],
    }


def _compact_source_handoff_text(value: Any, *, limit: int = 800) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _source_handoff_tokens(value: Any) -> list[str]:
    tokens = re.findall(
        r"[A-Za-z][A-Za-z0-9_+\-./]*|[\u0370-\u03ff]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?",
        str(value or "").lower(),
    )
    ignored = set(_GAP_PROVENANCE_STOPWORDS) | set(_MECHANISM_NOISE_TERMS)
    return [
        token for token in tokens
        if token not in ignored and (len(token) >= 3 or re.search(r"[\u0370-\u03ff\u4e00-\u9fff]", token))
    ]


def _source_text_mentions_value(source_text: Any, value: Any) -> bool:
    """Conservative local check used only to propose source-handoff roles."""
    text = _compact_source_handoff_text(source_text, limit=4000).lower()
    candidate = _compact_source_handoff_text(value, limit=400).lower()
    if not text or not candidate:
        return False
    if candidate in text:
        return True
    terms = list(dict.fromkeys(_source_handoff_tokens(candidate)))
    if not terms:
        return False
    hits = [term for term in terms if term in text]
    required = 1 if len(terms) == 1 else min(2, len(terms))
    return len(hits) >= required


def _handoff_source_location(unit: dict[str, Any]) -> dict[str, Any]:
    location = dict(unit.get("source_location") or {}) if isinstance(unit.get("source_location"), dict) else {}
    for key in ("source_field", "source_locator", "section", "sentence_start", "sentence_end", "span_start", "span_end"):
        value = unit.get(key)
        if value not in (None, "") and key not in location:
            location[key] = value
    return location


def _source_handoff_id(
    *,
    gap_id: str,
    source_unit_id: str,
    source_origin: str,
    source_role: str,
    package_slot: str = "",
    evidence_graph_edge_id: str = "",
    gap_signal_id: str = "",
) -> str:
    payload = {
        "gap_id": gap_id,
        "source_unit_id": source_unit_id,
        "source_origin": source_origin,
        "source_role": source_role,
        "package_slot": package_slot,
        "evidence_graph_edge_id": evidence_graph_edge_id,
        "gap_signal_id": gap_signal_id,
    }
    return "sth_" + sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def _source_unit_to_text_handoff(
    project: dict[str, Any],
    gap: dict[str, Any],
    unit: dict[str, Any],
    *,
    source_origin: str,
    source_role: str,
    gap_signal: dict[str, Any] | None = None,
    evidence_graph_edge: dict[str, Any] | None = None,
    package_slot: str = "",
    acceptance_status: str = "DIAGNOSTIC_ONLY",
    rejection_reason: str = "",
) -> dict[str, Any] | None:
    if not isinstance(unit, dict):
        return None
    source_unit_id = str(unit.get("source_unit_id") or "").strip()
    paper_id = str(unit.get("paper_id") or "").strip()
    if not source_unit_id or not paper_id:
        return None
    signal = gap_signal if isinstance(gap_signal, dict) else {}
    edge = evidence_graph_edge if isinstance(evidence_graph_edge, dict) else {}
    excerpt = _compact_source_handoff_text(
        unit.get("excerpt")
        or signal.get("text")
        or signal.get("source_text")
        or "",
        limit=800,
    )
    edge_id = str(edge.get("edge_id") or edge.get("id") or "").strip()
    signal_id = str(signal.get("signal_id") or signal.get("gap_signal_id") or "").strip()
    handoff = {
        "schema_version": "source_text_handoff_v1",
        "source_text_handoff_id": _source_handoff_id(
            gap_id=str(gap.get("gap_id") or ""),
            source_unit_id=source_unit_id,
            source_origin=source_origin,
            source_role=source_role,
            package_slot=package_slot,
            evidence_graph_edge_id=edge_id,
            gap_signal_id=signal_id,
        ),
        "project_id": str(project.get("project_id") or project.get("id") or gap.get("project_id") or ""),
        "gap_id": str(gap.get("gap_id") or ""),
        "sub_hypothesis_id": str(
            unit.get("sub_hypothesis_id")
            or gap.get("sub_hypothesis_id")
            or signal.get("sub_hypothesis_id")
            or ""
        ),
        "candidate_identity": str(gap.get("candidate_identity") or ""),
        "source_origin": source_origin,
        "source_role": source_role,
        "paper_id": paper_id,
        "source_unit_id": source_unit_id,
        "excerpt_hash": str(unit.get("excerpt_hash") or signal.get("excerpt_hash") or ""),
        "source_field": str(unit.get("source_field") or signal.get("source_field") or ""),
        "source_type": str(unit.get("source_type") or "fulltext"),
        "source_location": _handoff_source_location(unit),
        "bounded_excerpt": excerpt,
        "binding_status": str(unit.get("binding_status") or ""),
        "evidence_graph_edge_id": edge_id,
        "gap_signal_id": signal_id,
        "gap_signal_type": str(signal.get("signal_type") or signal.get("type") or ""),
        "gap_signal_text": _compact_source_handoff_text(
            signal.get("text") or signal.get("source_text") or "",
            limit=500,
        ),
        "acceptance_status": acceptance_status,
        "package_slot": package_slot,
        "rejection_reason": rejection_reason,
    }
    return handoff


def _dedupe_source_text_handoffs(handoffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in handoffs:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("source_unit_id") or ""),
            str(item.get("source_origin") or ""),
            str(item.get("source_role") or ""),
            str(item.get("evidence_graph_edge_id") or ""),
            str(item.get("gap_signal_id") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_source_text_handoffs(
    project: dict[str, Any],
    gap: dict[str, Any],
    *,
    source_units: list[dict[str, Any]] | None = None,
    causal_fields: dict[str, Any] | None = None,
    source_origin: str = "source_evidence_unit",
    gap_signal: dict[str, Any] | None = None,
    evidence_graph_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Carry source-unit text forward without assigning package slots.

    The handoff records are diagnostic lineage.  The bundle builder must still
    re-validate role semantics before a source unit can support input,
    mechanism, outcome, or measurement slots.
    """
    handoffs: list[dict[str, Any]] = []
    units = [dict(item) for item in (source_units or []) if isinstance(item, dict)]
    unit_by_id = {
        str(unit.get("source_unit_id") or ""): unit
        for unit in units
        if str(unit.get("source_unit_id") or "")
    }
    if gap_signal and not units:
        candidate = {
            "paper_id": gap_signal.get("paper_id"),
            "source_unit_id": gap_signal.get("source_unit_id"),
            "excerpt_hash": gap_signal.get("excerpt_hash"),
            "excerpt": gap_signal.get("text") or gap_signal.get("source_text"),
            "source_field": gap_signal.get("source_field"),
            "source_location": gap_signal.get("source_location"),
            "binding_status": gap_signal.get("source_text_status") or "SOURCE_UNIT_VERIFIED",
        }
        if candidate.get("paper_id") and candidate.get("source_unit_id"):
            units.append(candidate)
            unit_by_id[str(candidate["source_unit_id"])] = candidate
    for unit in units:
        handoff = _source_unit_to_text_handoff(
            project,
            gap,
            unit,
            source_origin=source_origin,
            source_role="gap_predicate" if gap_signal else "source_evidence_unit",
            gap_signal=gap_signal,
        )
        if handoff:
            handoffs.append(handoff)

    fields = causal_fields if isinstance(causal_fields, dict) else {}
    field_values = {
        "input": str((fields.get("input") or {}).get("value") if isinstance(fields.get("input"), dict) else fields.get("input") or ""),
        "mediator": str((fields.get("mediator") or {}).get("value") if isinstance(fields.get("mediator"), dict) else fields.get("mediator") or ""),
        "outcome": str((fields.get("outcome") or {}).get("value") if isinstance(fields.get("outcome"), dict) else fields.get("outcome") or ""),
    }
    edge_units_seen: set[str] = set()
    for edge in evidence_graph_edges or []:
        if not isinstance(edge, dict):
            continue
        unit = edge.get("source_evidence") if isinstance(edge.get("source_evidence"), dict) else {}
        source_unit_id = str(unit.get("source_unit_id") or "")
        if not unit and source_unit_id in unit_by_id:
            unit = unit_by_id[source_unit_id]
        if not unit:
            # Some persisted edge specs only carry the unit in the top-level
            # candidate list.  Bind by the unique unit id when available.
            candidate_ids: list[str] = []
            for role in ("source", "target"):
                endpoint = edge.get(role) if isinstance(edge.get(role), dict) else {}
                candidate_ids.extend(
                    str(item)
                    for item in (endpoint.get("provenance") or [])
                    if str(item)
                )
            unit = next((unit_by_id[item] for item in candidate_ids if item in unit_by_id), {})
        if not isinstance(unit, dict) or not unit.get("source_unit_id"):
            continue
        edge_units_seen.add(str(unit.get("source_unit_id") or ""))
        base = _source_unit_to_text_handoff(
            project,
            gap,
            unit,
            source_origin="evidence_graph_edge",
            source_role="evidence_edge",
            evidence_graph_edge=edge,
        )
        if base:
            handoffs.append(base)
        excerpt = unit.get("excerpt") or ""
        for role, value in field_values.items():
            if not value or not _source_text_mentions_value(excerpt, value):
                continue
            role_handoff = _source_unit_to_text_handoff(
                project,
                gap,
                unit,
                source_origin="evidence_graph_edge",
                source_role=role,
                evidence_graph_edge=edge,
            )
            if role_handoff:
                handoffs.append(role_handoff)

    gap_type = str(gap.get("gap_type") or "")
    gap_class = str(gap.get("gap_class") or "")
    if gap_type == "measurement_gap" or gap_class == "MEASUREMENT_GAP":
        outcome_value = field_values.get("outcome", "")
        for unit in units:
            if str(unit.get("source_unit_id") or "") in edge_units_seen:
                excerpt = unit.get("excerpt") or ""
            else:
                excerpt = unit.get("excerpt") or ""
            if not outcome_value or not _source_text_mentions_value(excerpt, outcome_value):
                continue
            handoff = _source_unit_to_text_handoff(
                project,
                gap,
                unit,
                source_origin="measurement_gap",
                source_role="measurement",
            )
            if handoff:
                handoffs.append(handoff)
    return _dedupe_source_text_handoffs(handoffs)


def normalize_source_text_handoffs(handoffs: Any) -> list[dict[str, Any]]:
    return _dedupe_source_text_handoffs([dict(item) for item in (handoffs or []) if isinstance(item, dict)])


def _compact_source_text_handoff_lineage_ref(handoff: Any) -> dict[str, Any]:
    source = handoff if isinstance(handoff, dict) else {}
    return {
        "schema_version": "evidence_lineage_ref_v1",
        "source_text_handoff_id": str(source.get("source_text_handoff_id") or ""),
        "paper_id": str(source.get("paper_id") or ""),
        "source_unit_id": str(source.get("source_unit_id") or ""),
        "excerpt_hash": str(source.get("excerpt_hash") or ""),
        "source_field": str(source.get("source_field") or ""),
        "source_origin": str(source.get("source_origin") or ""),
        "source_role": str(source.get("source_role") or ""),
        "binding_status": str(source.get("binding_status") or ""),
        "evidence_graph_edge_id": str(source.get("evidence_graph_edge_id") or ""),
        "gap_signal_id": str(source.get("gap_signal_id") or ""),
        "gap_signal_type": str(source.get("gap_signal_type") or ""),
        "acceptance_status": str(source.get("acceptance_status") or ""),
        "package_slot": str(source.get("package_slot") or ""),
        "rejection_reason": str(source.get("rejection_reason") or ""),
    }


def compact_source_text_handoff_lineage(handoffs: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in handoffs if isinstance(handoffs, list) else []:
        if not isinstance(item, dict):
            continue
        ref = _compact_source_text_handoff_lineage_ref(item)
        key = (
            str(ref.get("source_text_handoff_id") or ""),
            str(ref.get("source_unit_id") or ""),
            str(ref.get("source_role") or ""),
            str(ref.get("package_slot") or ""),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs


def _source_bound_subhypothesis_handoffs(
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    for branch in report.get("branch_states", []) if isinstance(report.get("branch_states"), list) else []:
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("sub_hypothesis_id") or "")
        branch_candidates = [
            item for item in candidates
            if branch_id and branch_id in list(item.get("sub_hypothesis_ids") or [])
        ]
        routable = next(
            (
                item for item in branch_candidates
                if assessment_of(item).get("route") in {
                    GapRoute.PRIMARY_CANDIDATE.value,
                    GapRoute.TARGETED_RETRIEVAL.value,
                }
            ),
            None,
        )
        if routable:
            selected = routable
            assessment = assessment_of(selected)
            route = str(assessment.get("route") or "")
            handoffs.append(
                {
                    "sub_hypothesis_id": branch_id,
                    "focus": str(branch.get("focus") or ""),
                    "coverage_status": f"{assessment.get('gap_type')}_{route}",
                    "gap_id": str(selected.get("gap_id") or ""),
                    "gap_track": route,
                    "socrates_handoff_allowed": False,
                    "next_agent": "type_directed_retrieval" if route == GapRoute.TARGETED_RETRIEVAL.value else "research_package_builder",
                    "next_action": "run_type_directed_evidence_retrieval" if route == GapRoute.TARGETED_RETRIEVAL.value else "build_type_specific_research_package",
                    "eligible_for_final_object_claim": route == GapRoute.PRIMARY_CANDIDATE.value,
                    "claim_strength_effect": str(selected.get("claim_strength_effect") or ""),
                }
            )
        else:
            handoffs.append(
                {
                    "sub_hypothesis_id": branch_id,
                    "focus": str(branch.get("focus") or ""),
                    "coverage_status": str(branch.get("state") or "GAP_NOT_RECOVERED_FROM_EVIDENCE"),
                    "gap_id": "",
                    "gap_track": "",
                    "socrates_handoff_allowed": False,
                    "required_upstream_action": str(branch.get("next_action") or ""),
                    "first_blocking_stage": str(branch.get("first_blocking_stage") or ""),
                    "reason": "No source-bound edge-level gap was recovered for this branch.",
                }
            )
    return handoffs


def to_landscape_diagnostic(item: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """Convert a sparse-map observation into a non-gap diagnostic artifact.

    Diagnostics intentionally have no gap id, novelty score, feasibility, or
    hypothesis-generation authority. They describe where to inspect the map;
    they do not assert that the scientific world contains a missing fact.
    """
    description = str(item.get("description") or item.get("gap_description") or "").strip()
    method = str(item.get("method") or "").strip()
    scenario = str(item.get("scenario") or "").strip()
    diagnostic_key = json.dumps(
        {
            "type": str(item.get("gap_type") or item.get("diagnostic_type") or "coverage_observation"),
            "description": description,
            "method": method,
            "scenario": scenario,
            "source": source,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "diagnostic_id": f"landscape_{sha256(diagnostic_key.encode('utf-8')).hexdigest()[:16]}",
        "artifact_type": "LANDSCAPE_DIAGNOSTIC",
        "diagnostic_type": str(item.get("gap_type") or item.get("diagnostic_type") or "coverage_observation"),
        "description": description,
        "method": method,
        "scenario": scenario,
        "supporting_references": [str(ref) for ref in (item.get("supporting_references") or []) if str(ref).strip()][:8],
        "semantic_plausibility": dict(item.get("semantic_plausibility") or {}) if isinstance(item.get("semantic_plausibility"), dict) else {},
        "source": source,
        "may_enter_socrates": False,
        "may_enter_mingli": False,
        "reason": "A coverage or cross-domain map observation is not, by itself, evidence of a scientific unknown.",
    }


def select_socrates_mechanism_verification_leads(
    mechanism_leads: list[dict[str, Any]],
    *,
    max_leads: int,
) -> list[dict[str, Any]]:
    """Select at most one scientifically valid verification lead per branch.

    A lead is allowed to spend one bounded Socrates search only when its entity,
    temporal, and LLM audits already pass.  The missing item is evidence for the
    causal transmission itself.  It never becomes a primary gap or hypothesis
    ingredient merely because it was selected for verification.
    """
    eligible: list[dict[str, Any]] = []
    for lead in mechanism_leads:
        if not isinstance(lead, dict) or not isinstance(lead.get("causal_mediation"), dict):
            continue
        audit = lead.get("scientific_causal_gap_audit") if isinstance(lead.get("scientific_causal_gap_audit"), dict) else {}
        hard = audit.get("hard_rule_audit") if isinstance(audit.get("hard_rule_audit"), dict) else {}
        temporal = audit.get("temporal_order") if isinstance(audit.get("temporal_order"), dict) else {}
        if not (
            audit.get("passes_for_socrates") is True
            and hard.get("passes") is True
            and temporal.get("passes") is True
        ):
            continue
        source_units = {
            str(item.get("source_unit_id") or item.get("excerpt_hash") or "")
            for item in (lead.get("source_evidence_units") or [])
            if isinstance(item, dict) and str(item.get("source_unit_id") or item.get("excerpt_hash") or "")
        }
        references = {str(value) for value in (lead.get("supporting_references") or []) if str(value)}
        score = (
            6.0
            + min(2.0, float(len(source_units)))
            + min(1.5, 0.5 * float(len(references)))
            + min(2.0, float(lead.get("exploration_value_score") or 0.0) / 5.0)
        )
        lead["mechanism_verification_priority"] = round(score, 3)
        eligible.append(lead)
    eligible.sort(
        key=lambda item: (
            -float(item.get("mechanism_verification_priority") or 0.0),
            str(item.get("sub_hypothesis_id") or ""),
            str(item.get("gap_id") or ""),
        )
    )
    selected: list[dict[str, Any]] = []
    selected_branches: set[str] = set()
    for lead in eligible:
        branch_id = normalized_subhypothesis_id(lead.get("sub_hypothesis_id"))
        branch_key = branch_id or f"unassigned:{lead.get('gap_id') or id(lead)}"
        if branch_key in selected_branches:
            continue
        selected_branches.add(branch_key)
        lead["gap_track"] = "MECHANISM_DISCOVERY_VERIFICATION_LEAD"
        lead["scientific_state"] = "MECHANISM_TRANSMISSION_UNVERIFIED"
        lead["socrates_targeted_retrieval_allowed"] = True
        lead["socrates_retrieval_mode"] = "MECHANISM_VERIFICATION_ONLY"
        lead["socrates_verification_budget"] = {"searches": 1, "imports": 3}
        lead["eligible_for_hypothesis_generation"] = False
        lead["may_fill_primary_evidence_slots"] = False
        lead["verification_question"] = (
            "Does source-bound literature directly verify the proposed A→M→Y transmission, temporal order, "
            "and a discriminating intervention or counterfactual test?"
        )
        selected.append(lead)
        if len(selected) >= max(0, int(max_leads)):
            break
    return selected


def _gap_console_summary(gap: dict[str, Any]) -> dict[str, Any]:
    causal = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    fields = causal.get("causal_fields") if isinstance(causal.get("causal_fields"), dict) else {}
    source = gap.get("source_alignment_verdict") if isinstance(gap.get("source_alignment_verdict"), dict) else {}
    epistemic = gap.get("gap_epistemic_verdict") if isinstance(gap.get("gap_epistemic_verdict"), dict) else {}
    source_units = [item for item in (gap.get("source_evidence_units") or []) if isinstance(item, dict)]

    def role_value(role: str) -> str:
        item = fields.get(role) if isinstance(fields.get(role), dict) else {}
        return re.sub(r"\s+", " ", str(item.get("value") or "")).strip()[:120]

    failures = [str(item) for item in (causal.get("failure_verdicts") or []) if str(item)]
    if not failures and causal.get("verdict") and causal.get("verdict") != "CAUSAL_CHAIN_VALID":
        failures = [str(causal.get("verdict"))]
    if epistemic.get("verdict") in {"NO_GAP_PREDICATE", "ANOMALY_CORROBORATION_REQUIRED"}:
        next_action = "retrieve_or_verify_source_bound_problem_unknown_contradiction_or_boundary_evidence"
    elif "SOURCE_ROLE_CONFLICT" in failures:
        next_action = "repair_paper_source_unit_and_subhypothesis_provenance"
    elif any(item in failures for item in ("INPUT_INVALID", "MEDIATOR_INVALID", "OUTCOME_INVALID")):
        next_action = "atomize_and_operationalize_input_mediator_outcome"
    elif "MODE_UNRESOLVED" in failures:
        next_action = "declare_source_supported_research_design"
    else:
        next_action = "review_candidate_contract"
    return {
        "gap_id": str(gap.get("gap_id") or ""),
        "candidate_identity": str(gap.get("candidate_identity") or ""),
        "state_version": int(
            ((gap.get("gap_provenance") or {}).get("state_version"))
            or gap.get("state_version")
            or 0
        ),
        "SH": normalized_subhypothesis_id(gap.get("sub_hypothesis_id")) or "(missing)",
        "type": str(gap.get("gap_type") or gap.get("candidate_type") or ""),
        "description": re.sub(
            r"\s+", " ", str(gap.get("description") or gap.get("gap_description") or "")
        ).strip()[:180],
        "A": role_value("input"),
        "M": role_value("mediator"),
        "Y": role_value("outcome"),
        "source": str(source.get("verdict") or "UNVERIFIABLE_SOURCE"),
        "epistemic": str(epistemic.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
        "causal": str(causal.get("verdict") or "SOURCE_ROLE_CONFLICT"),
        "primary_failure": failures[0] if failures else "",
        "all_failures": failures,
        "pool": str(gap.get("gap_candidate_pool") or gap.get("scientific_state") or ""),
        "source_units": len(source_units),
        "next_action": next_action,
    }


def _near_pass_branch_context(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Resolve only declared SH anchors; never invent causal roles for search."""
    branch_id = normalized_subhypothesis_id(gap.get("sub_hypothesis_id"))
    branch = next(
        (
            item for item in (project.get("sub_hypotheses") or [])
            if isinstance(item, dict)
            and normalized_subhypothesis_id(item.get("id") or item.get("sub_hypothesis_id")) == branch_id
        ),
        {},
    )
    contracts = project.get("subhypothesis_alignment_contracts") if isinstance(project.get("subhypothesis_alignment_contracts"), dict) else {}
    contract = contracts.get(branch_id) if isinstance(contracts.get(branch_id), dict) else {}
    causal_contract = branch.get("causal_contract") if isinstance(branch.get("causal_contract"), dict) else {}
    fields = (
        (gap.get("causal_readiness_verdict") or {}).get("causal_fields")
        if isinstance((gap.get("causal_readiness_verdict") or {}).get("causal_fields"), dict)
        else {}
    )

    def field_value(name: str) -> str:
        value = fields.get(name) if isinstance(fields.get(name), dict) else {}
        return str(value.get("value") or "").strip()

    input_anchor = (
        field_value("input")
        or str(gap.get("intervention") or "").strip()
        or str(contract.get("focal_variable") or contract.get("scientific_object") or "").strip()
        or str(branch.get("focus") or "").strip()
    )
    outcome_anchor = (
        field_value("outcome")
        or str(gap.get("outcome") or "").strip()
        or str(causal_contract.get("outcome") or "").strip()
        or "; ".join(str(value) for value in (branch.get("dependent_variables") or []) if str(value).strip())
    )
    comparison_anchor = (
        str(gap.get("comparison") or "").strip()
        or str(branch.get("comparison") or branch.get("baseline_or_comparator") or "").strip()
        or "; ".join(str(value) for value in (branch.get("comparison_conditions") or []) if str(value).strip())
    )
    return {
        "sub_hypothesis_id": branch_id,
        "input": input_anchor,
        "outcome": outcome_anchor,
        "comparison": comparison_anchor,
        "scientific_object": str(contract.get("scientific_object") or branch.get("focus") or "").strip(),
        "declared_research_mode": str(
            branch.get("declared_research_mode")
            or causal_contract.get("primary_epistemic_mode")
            or ""
        ).strip(),
    }


def build_near_pass_targeted_retrieval_task(
    project: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    """Plan one bounded evidence-role repair for an eligible near-pass gap.

    This is deliberately stricter than a generic literature search.  A task
    is issued only when the candidate already has a declared SH intervention,
    outcome, and comparison anchor, and when the failure is repairable by a
    direct source-unit search.  It cannot rescue an out-of-scope paper or a
    descriptive method sentence such as the BiFeO3/VSM false positive.
    """
    item = dict(gap or {})
    context = _near_pass_branch_context(project, item)
    source = item.get("source_alignment_verdict") if isinstance(item.get("source_alignment_verdict"), dict) else {}
    epistemic = item.get("gap_epistemic_verdict") if isinstance(item.get("gap_epistemic_verdict"), dict) else {}
    causal = item.get("causal_readiness_verdict") if isinstance(item.get("causal_readiness_verdict"), dict) else {}
    failures = [str(value) for value in (causal.get("failure_verdicts") or []) if str(value)]
    source_units = [unit for unit in (item.get("source_evidence_units") or []) if isinstance(unit, dict)]
    source_bound = bool(source_units) and all(str(unit.get("paper_id") or "").strip() for unit in source_units)
    source_verdict = str(source.get("verdict") or "UNVERIFIABLE_SOURCE")
    epistemic_verdict = str(epistemic.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE")
    excluded_reasons: list[str] = []
    if source_verdict in {"OUT_OF_SCOPE", "RATIONALE_ALIGNED"}:
        excluded_reasons.append("SOURCE_NOT_DIRECT_OR_REPAIRABLE")
    if epistemic_verdict in {"NO_GAP_PREDICATE", "ANOMALY_CORROBORATION_REQUIRED"}:
        excluded_reasons.append("NO_SOURCE_BOUND_GAP_PREDICATE")
    if not source_bound:
        excluded_reasons.append("SOURCE_PAPER_ANCHOR_MISSING")
    if not context["sub_hypothesis_id"]:
        excluded_reasons.append("SUBHYPOTHESIS_ANCHOR_MISSING")
    if not context["input"] or not context["outcome"] or not context["comparison"]:
        excluded_reasons.append("DECLARED_INPUT_OUTCOME_OR_COMPARISON_MISSING")
    # Input-invalid candidates would require inventing the intervention.  Do
    # not spend external retrieval budget on that modelling task.
    if "INPUT_INVALID" in failures:
        excluded_reasons.append("INPUT_MUST_BE_REVISED_BEFORE_RETRIEVAL")
    repairable_failures = {
        "SOURCE_ROLE_CONFLICT",
        "MEDIATOR_INVALID",
        "OUTCOME_INVALID",
        "COMPARISON_INVALID",
        "MODE_UNRESOLVED",
    }
    if failures and not set(failures).issubset(repairable_failures):
        excluded_reasons.append("NON_RETRIEVAL_CAUSAL_FAILURE")
    missing_roles: list[str] = []
    if "MEDIATOR_INVALID" in failures:
        missing_roles.append("mediator")
    if "OUTCOME_INVALID" in failures:
        missing_roles.append("outcome")
    if "SOURCE_ROLE_CONFLICT" in failures or source_verdict == "UNVERIFIABLE_SOURCE":
        missing_roles.append("direct_source_unit")
    if not missing_roles:
        missing_roles.append("comparison_boundary")
    query_terms = [context["input"], context["outcome"], context["comparison"]]
    if "mediator" in missing_roles:
        query_terms.append("mechanism")
    if "comparison_boundary" in missing_roles or "direct_source_unit" in missing_roles:
        query_terms.append("comparison boundary limitation")
    query = " ".join(term for term in query_terms if term).strip()
    candidate_identity = str(item.get("candidate_identity") or "")
    return {
        "schema_version": "near_pass_targeted_retrieval_task_v1",
        "task_type": "NEAR_PASS_SOURCE_ROLE_REPAIR",
        "candidate_identity": candidate_identity,
        "gap_id": str(item.get("gap_id") or ""),
        "sub_hypothesis_id": context["sub_hypothesis_id"],
        "eligible": not excluded_reasons,
        "ineligibility_reasons": excluded_reasons,
        "retrieval_mode": "NEAR_PASS_SOURCE_ROLE_REPAIR",
        "query": query,
        "missing_evidence_roles": list(dict.fromkeys(missing_roles)),
        "retrieval_anchor_contract": {
            "scientific_object": context["scientific_object"],
            "input": context["input"],
            "outcome": context["outcome"],
            "comparison": context["comparison"],
            "research_mode": context["declared_research_mode"],
            "required_source_role": "direct",
            "required_binding_status": "SOURCE_UNIT_VERIFIED",
        },
        "source_paper_ids": list(dict.fromkeys(
            str(unit.get("paper_id") or "") for unit in source_units if str(unit.get("paper_id") or "")
        )),
        "budget": {"searches": 1, "imports": 3, "full_text_repairs": 3},
        "promotion_policy": (
            "Retrieved text may upgrade this candidate only after source-unit binding, role alignment, explicit gap-predicate, "
            "causal A-M-Y, comparison, and normal TanXi re-audit all pass. Retrieval alone never promotes the gap."
        ),
    }


def build_contentful_causal_contract_repair_task(
    project: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    """Plan a bounded LLM+literature repair for contentful role-incomplete gaps.

    This lane is for candidates that are not near-pass under the strict direct
    source-role contract because they are missing the causal role contract
    itself (often ``INPUT_INVALID`` plus mediator/outcome/comparison failures).
    It asks retrieval/LLM to bind roles, but still routes any successful repair
    back through TanXi; it never promotes a candidate by itself.
    """
    item = dict(gap or {})
    context = _near_pass_branch_context(project, item)
    causal = item.get("causal_readiness_verdict") if isinstance(item.get("causal_readiness_verdict"), dict) else {}
    failures = [str(value) for value in (causal.get("failure_verdicts") or []) if str(value)]
    source = item.get("source_alignment_verdict") if isinstance(item.get("source_alignment_verdict"), dict) else {}
    epistemic = item.get("gap_epistemic_verdict") if isinstance(item.get("gap_epistemic_verdict"), dict) else {}
    seed_contract = item.get("mechanism_seed_contract") if isinstance(item.get("mechanism_seed_contract"), dict) else {}
    source_units = [unit for unit in (item.get("source_evidence_units") or []) if isinstance(unit, dict)]
    description = str(item.get("gap_description") or item.get("description") or "").strip()
    supporting_refs = [str(value) for value in (item.get("supporting_references") or []) if str(value).strip()]
    contentful_source = bool(
        source_units
        or supporting_refs
        or str(source.get("verdict") or "") in {
            "DIRECTLY_ALIGNED",
            "PARTIALLY_ALIGNED",
            "RATIONALE_ALIGNED",
            "COMPONENT_BRIDGE_CONTEXT_BOUND",
            "UNVERIFIABLE_SOURCE",
        }
        or str(epistemic.get("verdict") or "") in {
            "EXPLICIT_AUTHOR_STATED_GAP",
            "COMPOSITE_CONTRADICTION_GAP",
            "THEORY_OBSERVATION_MISMATCH",
            "COMPONENT_BRIDGE_CONTEXT_WITHOUT_FINAL_DIRECT_CORE_VALIDATION",
            "EVIDENCE_EXTRACTION_SHORTAGE",
        }
        or str(seed_contract.get("status") or "") in {
            "COMPLETE_COMPOSITE_MECHANISM_SEED",
            "INCOMPLETE_MECHANISM_SEED",
        }
    )
    role_failure_codes = {
        "INPUT_INVALID": "input",
        "MEDIATOR_INVALID": "mediator",
        "OUTCOME_INVALID": "outcome",
        "COMPARISON_INVALID": "comparison",
        "SOURCE_ROLE_CONFLICT": "direct_source_unit",
        "MODE_UNRESOLVED": "research_mode",
    }
    missing_roles = [
        role
        for code, role in role_failure_codes.items()
        if code in failures
    ]
    for role, value in (
        ("input", context.get("input")),
        ("outcome", context.get("outcome")),
        ("comparison", context.get("comparison")),
    ):
        if not value and role not in missing_roles:
            missing_roles.append(role)
    if "mediator" not in missing_roles and not str(item.get("mediator") or item.get("proposed_mediator") or "").strip():
        missing_roles.append("mediator")
    excluded_reasons: list[str] = []
    if len(description) < 60:
        excluded_reasons.append("CONTENTFUL_DESCRIPTION_MISSING")
    if not contentful_source:
        excluded_reasons.append("SOURCE_OR_GAP_PREDICATE_ANCHOR_MISSING")
    if not context["sub_hypothesis_id"]:
        excluded_reasons.append("SUBHYPOTHESIS_ANCHOR_MISSING")
    if not missing_roles:
        excluded_reasons.append("NO_CAUSAL_ROLE_REPAIR_NEEDED")
    if item.get("gap_candidate_pool") == LANDSCAPE_DIAGNOSTIC_POOL or str(item.get("gap_track") or "") == "LANDSCAPE_DIAGNOSTIC":
        excluded_reasons.append("LANDSCAPE_DIAGNOSTIC_NOT_ROLE_REPAIRABLE")
    if str(item.get("gap_track") or "") == "PRIMARY_SCIENTIFIC_GAP" or item.get("primary_eligible") is True:
        excluded_reasons.append("ALREADY_PRIMARY_OR_PRIMARY_ELIGIBLE")
    query_terms = [
        description,
        context.get("scientific_object"),
        context.get("input"),
        context.get("outcome"),
        context.get("comparison"),
        "mechanism causal mediator outcome comparison limitation",
    ]
    query = " ".join(term for term in query_terms if str(term or "").strip())
    query = " ".join(query.split())[:900]
    candidate_identity = str(item.get("candidate_identity") or "")
    return {
        "schema_version": "near_pass_targeted_retrieval_task_v1",
        "task_type": "CONTENTFUL_CAUSAL_CONTRACT_REPAIR",
        "candidate_identity": candidate_identity,
        "gap_id": str(item.get("gap_id") or ""),
        "sub_hypothesis_id": context["sub_hypothesis_id"],
        "eligible": not excluded_reasons,
        "ineligibility_reasons": excluded_reasons,
        "retrieval_mode": "CONTENTFUL_CAUSAL_CONTRACT_REPAIR",
        "query": query,
        "requires_llm_role_completion": True,
        "missing_evidence_roles": list(dict.fromkeys(missing_roles)),
        "retrieval_anchor_contract": {
            "scientific_object": context["scientific_object"],
            "input": context["input"],
            "outcome": context["outcome"],
            "comparison": context["comparison"],
            "research_mode": context["declared_research_mode"],
            "required_source_role": "role_binding_or_direct_source_unit",
            "required_binding_status": "SOURCE_UNIT_VERIFIED",
            "repair_target": "input_mediator_outcome_comparison_contract",
        },
        "source_paper_ids": list(dict.fromkeys(
            str(unit.get("paper_id") or "") for unit in source_units if str(unit.get("paper_id") or "")
        )),
        "supporting_references": supporting_refs[:12],
        "budget": {"searches": 1, "imports": 3, "full_text_repairs": 3},
        "promotion_policy": (
            "Use LLM-assisted extraction and targeted literature search only to propose source-bound "
            "input/mediator/outcome/comparison role bindings. A repaired candidate may become primary "
            "only after verified source-unit binding and a normal TanXi re-audit; this task never promotes it directly."
        ),
    }


def select_near_pass_targeted_retrieval_tasks(
    project: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    max_tasks: int = 3,
) -> list[dict[str, Any]]:
    """Choose a small, deterministic set of repairable near-pass tasks."""
    tasks = [
        build_near_pass_targeted_retrieval_task(project, candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    strict_eligible = [task for task in tasks if task.get("eligible") is True and str(task.get("query") or "")]
    strict_eligible.sort(key=lambda task: (
        len(task.get("missing_evidence_roles") or []),
        str(task.get("sub_hypothesis_id") or ""),
        str(task.get("candidate_identity") or task.get("gap_id") or ""),
    ))
    contentful_tasks = [
        build_contentful_causal_contract_repair_task(project, candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    contentful_eligible = [
        task for task in contentful_tasks
        if task.get("eligible") is True and str(task.get("query") or "")
    ]
    contentful_eligible.sort(key=lambda task: (
        -int("direct_source_unit" in set(task.get("missing_evidence_roles") or [])),
        -int(bool(task.get("source_paper_ids") or task.get("supporting_references"))),
        str(task.get("sub_hypothesis_id") or ""),
        str(task.get("gap_id") or ""),
        str(task.get("candidate_identity") or ""),
    ))
    eligible = contentful_eligible[: max(0, min(3, int(max_tasks)))] + strict_eligible
    deduplicated: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    for task in eligible:
        identity = str(task.get("candidate_identity") or task.get("gap_id") or "")
        if not identity or identity in seen_identities:
            continue
        seen_identities.add(identity)
        deduplicated.append(task)
    return deduplicated[: max(0, int(max_tasks))]


def apply_near_pass_targeted_retrieval_result(
    project: dict[str, Any],
    gap: dict[str, Any],
    retrieval_result: dict[str, Any],
) -> dict[str, Any]:
    """Re-audit retrieved evidence without granting an automatic promotion.

    The retrieval executor must return explicit, source-bound role bindings.
    Metadata hits and unstructured abstracts are recorded as unsuccessful
    repairs.  Successful structured repairs re-enter the existing immutable
    source-role and TanXi gates; only that re-audit may raise the candidate's
    scientific state.
    """
    try:
        from ._gap_governance import assign_gap_candidate_provenance, annotate_gap_governance
        from ._gap_source_role import audit_and_route_original_gap_source
    except ImportError:
        from _gap_governance import assign_gap_candidate_provenance, annotate_gap_governance
        from _gap_source_role import audit_and_route_original_gap_source

    original = dict(gap or {})
    task = build_near_pass_targeted_retrieval_task(project, original)
    if task.get("eligible") is not True:
        contentful_task = build_contentful_causal_contract_repair_task(project, original)
        if contentful_task.get("eligible") is True:
            task = contentful_task
    result = dict(retrieval_result or {})
    units = [unit for unit in (result.get("source_evidence_units") or []) if isinstance(unit, dict)]
    role_bindings = result.get("causal_role_bindings") if isinstance(result.get("causal_role_bindings"), dict) else {}
    comparison = str(result.get("comparison") or "").strip()

    def valid_binding(role: str) -> bool:
        binding = role_bindings.get(role) if isinstance(role_bindings.get(role), dict) else {}
        refs = [str(value) for value in (binding.get("source_unit_ids") or []) if str(value)]
        return bool(str(binding.get("value") or "").strip() and refs)

    verified_units = bool(units) and all(
        str(unit.get("paper_id") or "").strip()
        and str(unit.get("source_unit_id") or "").strip()
        and str(unit.get("binding_status") or "") == "SOURCE_UNIT_VERIFIED"
        for unit in units
    )
    complete_repair = bool(
        task.get("eligible") is True
        and verified_units
        and all(valid_binding(role) for role in ("input", "mediator", "outcome"))
        and comparison
    )
    if not complete_repair:
        original["near_pass_targeted_retrieval"] = {
            "task": task,
            "status": "RETRIEVAL_COMPLETED_NOT_REPAIRABLE",
            "reason": "Returned evidence did not supply verified direct source units plus all A-M-Y and comparison bindings.",
            "retrieval_result": result,
        }
        assign_gap_candidate_provenance(project, original)
        return annotate_gap_governance(original)

    repaired = dict(original)
    repaired["original_source_role_audit_before_targeted_retrieval"] = dict(
        original.get("original_source_role_audit") or {}
    )
    merged_units = [unit for unit in (original.get("source_evidence_units") or []) if isinstance(unit, dict)] + units
    by_unit = {
        str(unit.get("source_unit_id") or unit.get("excerpt_hash") or index): unit
        for index, unit in enumerate(merged_units)
    }
    repaired["source_evidence_units"] = list(by_unit.values())[:24]
    repaired["intervention"] = str(role_bindings["input"]["value"]).strip()
    repaired["proposed_mediator"] = str(role_bindings["mediator"]["value"]).strip()
    repaired["outcome"] = str(role_bindings["outcome"]["value"]).strip()
    repaired["comparison"] = comparison
    repaired["causal_mediation"] = {
        "known": {
            "A_to_B": {
                "source": repaired["intervention"],
                "target": repaired["proposed_mediator"],
                "source_unit_ids": list(role_bindings["input"].get("source_unit_ids") or []),
            },
            "B_to_C": {
                "source": repaired["proposed_mediator"],
                "target": repaired["outcome"],
                "source_unit_ids": list(role_bindings["outcome"].get("source_unit_ids") or []),
            },
        }
    }
    repaired["near_pass_targeted_retrieval"] = {
        "task": task,
        "status": "STRUCTURED_REPAIR_READY_FOR_REAUDIT",
        "retrieval_result": result,
        "repaired_at": time.time(),
    }
    routed = audit_and_route_original_gap_source(project, repaired)
    routed["near_pass_targeted_retrieval"]["status"] = "RETRIEVAL_REAUDITED"
    routed["near_pass_targeted_retrieval"]["scientific_state_after_reaudit"] = str(routed.get("scientific_state") or "")
    assign_gap_candidate_provenance(project, routed)
    return annotate_gap_governance(routed)


def log_tanxi_gap_diagnostic_samples(
    project: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    rejected_candidates: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> None:
    """Emit bounded summaries that expose why candidate counts are not gaps."""

    rows = [item for item in candidates if isinstance(item, dict)]
    project_id = str(project.get("project_id") or "")

    def failure_count(item: dict[str, Any]) -> int:
        causal = item.get("causal_readiness_verdict") if isinstance(item.get("causal_readiness_verdict"), dict) else {}
        return len(causal.get("failure_verdicts") or [])

    near_pass = sorted(
        [
            item for item in rows
            if not bool((item.get("gap_epistemic_verdict") or {}).get("passes"))
            or not bool((item.get("causal_readiness_verdict") or {}).get("passes"))
        ],
        key=lambda item: (
            failure_count(item),
            0 if str((item.get("source_alignment_verdict") or {}).get("verdict") or "") == "DIRECTLY_ALIGNED" else 1,
            str(item.get("gap_id") or ""),
        ),
    )[: max(0, int(limit))]
    for item in near_pass:
        log_event("SCIENCE", "tanxi_near_pass_gap", project_id=project_id, **_gap_console_summary(item))

    secondary = sorted(
        [item for item in rows if item.get("gap_candidate_pool") == SECONDARY_RESEARCH_OPPORTUNITY_POOL],
        key=lambda item: (
            0 if str((item.get("gap_epistemic_verdict") or {}).get("verdict") or "") == "NO_GAP_PREDICATE" else 1,
            0 if not normalized_subhypothesis_id(item.get("sub_hypothesis_id")) else 1,
            str(item.get("gap_id") or ""),
        ),
    )[: max(0, int(limit))]
    for item in secondary:
        log_event("SCIENCE", "tanxi_secondary_gap_sample", project_id=project_id, **_gap_console_summary(item))

    rejected = [item for item in (rejected_candidates or []) if isinstance(item, dict)]
    rejected.extend(
        item for item in rows
        if item.get("gap_candidate_pool") == REJECTED_SCIENTIFIC_CANDIDATE_POOL
    )
    for item in rejected[: max(0, int(limit))]:
        summary = _gap_console_summary(item)
        preflight = item.get("causal_preflight") if isinstance(item.get("causal_preflight"), dict) else {}
        if preflight:
            summary["all_failures"] = list(preflight.get("failure_reasons") or preflight.get("failures") or summary["all_failures"])
        log_event("SCIENCE", "tanxi_rejected_causal_sample", project_id=project_id, **summary)


def log_tabi_candidate_funnel(
    raw_candidates: list[dict[str, Any]],
    routed_candidates: list[dict[str, Any]],
    *,
    project: dict[str, Any] | None = None,
) -> None:
    raw = [item for item in raw_candidates if isinstance(item, dict)]
    record_index = _papergraph_record_index_for_gap_binding(project)
    routed = [
        item for item in routed_candidates
        if isinstance(item, dict) and str(item.get("gap_type") or "") == "implicit_tabi"
    ]
    log_event(
        "SCIENCE",
        "tabi_candidate_funnel",
        raw_patterns=len(raw),
        source_bound=sum(
            bool(item.get("source_evidence_units"))
            and all(unit.get("paper_id") and unit.get("source_unit_id") for unit in item.get("source_evidence_units") or [])
            for item in raw
        ),
        subhypothesis_bound=sum(
            bool(infer_gap_subhypothesis_id(item, project, record_index))
            for item in raw
        ),
        composite_contract_passed=sum(
            str((item.get("composite_evidence_contract") or {}).get("status") or "") == "PASSED"
            for item in routed
        ),
        temporal_passed=sum(bool((item.get("temporal_order_audit") or {}).get("passes")) for item in routed),
        entity_gate_passed=sum(bool((item.get("causal_readiness_verdict") or {}).get("passes")) for item in routed),
        scientifically_admitted=sum(
            bool((item.get("gap_epistemic_verdict") or {}).get("passes"))
            and bool((item.get("causal_readiness_verdict") or {}).get("passes"))
            for item in routed
        ),
    )
    composite_axis_failures: Counter[str] = Counter()
    pre_route_contract_failures: Counter[str] = Counter()
    temporal_failures: Counter[str] = Counter()
    entity_gate_failures: Counter[str] = Counter()
    near_pass_to_verification_lead = 0
    near_pass_to_source_unit_repair = 0
    near_pass_to_component_bridge_candidate = 0

    def _reason_key(value: Any, default: str = "unknown") -> str:
        text = " ".join(str(value or "").lower().replace("-", "_").split())
        if not text:
            return default
        if any(token in text for token in ("input", "intervention", "independent", "declared_input")):
            return "input_or_declared_input"
        if any(token in text for token in ("mediator", "mechanism", "process", "transmission")):
            return "mediator_or_mechanism"
        if any(token in text for token in ("outcome", "endpoint", "readout", "dependent", "output")):
            return "outcome_or_endpoint"
        if any(token in text for token in ("comparison", "baseline", "control", "counterfactual")):
            return "comparison_or_baseline"
        if any(token in text for token in ("temporal", "order", "before", "after", "sequence")):
            return "temporal_order"
        if any(token in text for token in ("source", "unit", "citation", "span", "excerpt", "provenance")):
            return "source_unit_binding"
        if "component_bridge" in text or "bridge" in text:
            return "component_bridge_restricted"
        return text[:80] or default

    # TABI patterns are intentionally pre-admission signals.  Previously the
    # detailed diagnostics only inspected routed candidates, making a
    # ``raw_patterns > 0, routed == 0`` run opaque.  Record contract failures
    # from the raw source-bound pattern itself before routing removes it.
    for item in raw:
        contract = item.get("composite_evidence_contract") if isinstance(item.get("composite_evidence_contract"), dict) else {}
        if str(contract.get("status") or "") == "PASSED":
            continue
        raw_reasons = (
            contract.get("missing_axes")
            or contract.get("missing_fields")
            or contract.get("failure_reasons")
            or contract.get("failures")
            or [contract.get("status") or "composite_contract_not_passed"]
        )
        reason_keys = [
            _reason_key(reason, "composite_contract_not_passed")
            for reason in raw_reasons if str(reason).strip()
        ]
        if not reason_keys:
            reason_keys = ["composite_contract_not_passed"]
        for reason_key in reason_keys:
            pre_route_contract_failures[reason_key] += 1
        log_event(
            "SCIENCE",
            "tabi_pre_route_contract_rejected",
            project_id=str((project or {}).get("project_id") or ""),
            gap_id=str(item.get("gap_id") or ""),
            sub_hypothesis_id=str(item.get("sub_hypothesis_id") or ""),
            reasons=reason_keys,
            contract_status=str(contract.get("status") or "NOT_PASSED"),
            action="retain_as_pre_admission_pattern_not_scientific_gap",
        )

    for item in routed:
        contract = item.get("composite_evidence_contract") if isinstance(item.get("composite_evidence_contract"), dict) else {}
        item_composite_reason_keys: list[str] = []
        if str(contract.get("status") or "") != "PASSED":
            raw_reasons = (
                contract.get("missing_axes")
                or contract.get("missing_fields")
                or contract.get("failure_reasons")
                or contract.get("failures")
                or [contract.get("status") or "composite_contract_not_passed"]
            )
            for reason in raw_reasons if isinstance(raw_reasons, list) else [raw_reasons]:
                key = _reason_key(reason, "composite_contract_not_passed")
                item_composite_reason_keys.append(key)
                composite_axis_failures[key] += 1
        temporal = item.get("temporal_order_audit") if isinstance(item.get("temporal_order_audit"), dict) else {}
        if temporal.get("passes") is not True:
            temporal_failures[_reason_key(temporal.get("reason") or temporal.get("verdict") or temporal.get("status"), "temporal_order_not_passed")] += 1
        causal = item.get("causal_readiness_verdict") if isinstance(item.get("causal_readiness_verdict"), dict) else {}
        if causal.get("passes") is not True:
            failures = causal.get("failure_verdicts") if isinstance(causal.get("failure_verdicts"), list) else []
            if not failures:
                failures = [causal.get("verdict") or "causal_entity_gate_not_passed"]
            for failure in failures:
                entity_gate_failures[_reason_key(failure, "causal_entity_gate_not_passed")] += 1
        pool = str(item.get("gap_candidate_pool") or "")
        if pool in {GAP_EXISTENCE_VERIFICATION_POOL, MECHANISM_DISCOVERY_LEAD_POOL} or item.get("socrates_targeted_retrieval_allowed") is True:
            near_pass_to_verification_lead += 1
        if pool == EVIDENCE_EXTRACTION_SHORTAGE_POOL or "source_unit_binding" in item_composite_reason_keys:
            near_pass_to_source_unit_repair += 1
        if (
            pool == COMPOSITE_GAP_AUDIT_POOL
            or str(causal.get("verdict") or "") == "COMPONENT_BRIDGE_RESTRICTED_GAP_READY"
            or item.get("component_bridge_gap_synthesis_ready") is True
        ):
            near_pass_to_component_bridge_candidate += 1
    log_event(
        "SCIENCE",
        "tabi_candidate_funnel_diagnostics",
        raw_patterns=len(raw),
        routed=len(routed),
        failed_pre_route_contract_by_reason=dict(pre_route_contract_failures.most_common(12)),
        failed_composite_contract_by_axis=dict(composite_axis_failures.most_common(12)),
        failed_temporal_by_reason=dict(temporal_failures.most_common(12)),
        failed_entity_gate_by_reason=dict(entity_gate_failures.most_common(12)),
        near_pass_to_verification_lead=near_pass_to_verification_lead,
        near_pass_to_source_unit_repair=near_pass_to_source_unit_repair,
        near_pass_to_component_bridge_candidate=near_pass_to_component_bridge_candidate,
    )


def log_subhypothesis_gap_handoff_summaries(
    project: dict[str, Any],
    handoffs: list[dict[str, Any]],
    routed_candidates: list[dict[str, Any]],
) -> None:
    project_id = str(project.get("project_id") or "")
    branches = {
        normalized_subhypothesis_id(item.get("id") or item.get("sub_hypothesis_id")): item
        for item in (project.get("sub_hypotheses") or [])
        if isinstance(item, dict) and normalized_subhypothesis_id(item.get("id") or item.get("sub_hypothesis_id"))
    }
    for handoff in handoffs:
        branch_id = normalized_subhypothesis_id(handoff.get("sub_hypothesis_id"))
        branch = branches.get(branch_id, {})
        retrieval = branch.get("retrieval") if isinstance(branch.get("retrieval"), dict) else {}
        coverage = (
            retrieval.get("cumulative_full_text_coverage")
            if isinstance(retrieval.get("cumulative_full_text_coverage"), dict)
            else {}
        )
        fulltext_count = int(
            coverage.get("imported_related_full_text_count")
            if coverage.get("imported_related_full_text_count") is not None
            else coverage.get("imported_full_text_count")
            if coverage.get("imported_full_text_count") is not None
            else retrieval.get("full_text_imported_records")
            or 0
        )
        fulltext_target = int(
            coverage.get("imported_related_full_text_target")
            if coverage.get("imported_related_full_text_target") is not None
            else coverage.get("imported_full_text_target")
            if coverage.get("imported_full_text_target") is not None
            else retrieval.get("full_text_import_target")
            or 10
        )
        fulltext_shortfall = int(
            coverage.get("imported_related_full_text_shortfall")
            if coverage.get("imported_related_full_text_shortfall") is not None
            else max(0, fulltext_target - fulltext_count)
        )
        auxiliary_material_total = int(
            coverage.get("auxiliary_material_total")
            if coverage.get("auxiliary_material_total") is not None
            else coverage.get("metadata_only_auxiliary_total")
            or 0
        )
        component_bridge_ready = bool(
            str(handoff.get("coverage_status") or "") == "COMPONENT_BRIDGE_GAP_READY"
            or handoff.get("gap_track") == "COMPONENT_BRIDGE_GAP_SYNTHESIS"
        )
        branch_candidates = [
            item for item in routed_candidates
            if normalized_subhypothesis_id(item.get("sub_hypothesis_id")) == branch_id
        ]
        log_event(
            "SCIENCE",
            "tanxi_subhypothesis_handoff",
            project_id=project_id,
            SH=branch_id,
            fulltext=f"{fulltext_count}/{fulltext_target}",
            fulltext_shortfall=fulltext_shortfall,
            auxiliary_material=auxiliary_material_total,
            component_bridge_gap_ready=component_bridge_ready,
            direct_core=int(retrieval.get("direct_target_evidence_imported_records") or 0),
            evidence_reserve=int(((retrieval.get("evidence_reserve") or {}).get("candidate_count") or 0)),
            explicit_gap_predicates=sum(bool((item.get("gap_epistemic_verdict") or {}).get("passes")) for item in branch_candidates),
            causal_candidates=sum(str(item.get("gap_type") or "") in {"causal_chain_break", "causal_mediation_unresolved"} for item in branch_candidates),
            primary_gaps=sum(item.get("gap_candidate_pool") == PRIMARY_MECHANISM_CANDIDATE_POOL for item in branch_candidates),
            verification_leads=sum(item.get("gap_candidate_pool") == MECHANISM_DISCOVERY_LEAD_POOL for item in branch_candidates),
            status=str(handoff.get("coverage_status") or ""),
            next_agent=str(handoff.get("next_agent") or ""),
            next_action=str(
                handoff.get("next_action")
                or handoff.get("required_upstream_action")
                or "none"
            ),
            hypothesis_generation_mode=str(handoff.get("hypothesis_generation_mode") or ""),
        )


def build_subhypothesis_gap_handoffs(
    project: dict[str, Any],
    primary_gaps: list[dict[str, Any]],
    targeted_gaps: list[dict[str, Any]],
    mechanism_leads: list[dict[str, Any]],
    extraction_shortages: list[dict[str, Any]],
    mechanism_verification_leads: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Represent every branch without fabricating one scientific gap per branch."""
    branches = [
        item for item in (project.get("sub_hypotheses") or [])
        if isinstance(item, dict) and normalized_subhypothesis_id(item.get("id") or item.get("sub_hypothesis_id"))
    ]
    valid = [item for item in primary_gaps + targeted_gaps if isinstance(item, dict)]
    verification = [item for item in (mechanism_verification_leads or []) if isinstance(item, dict)]
    verification_ids = {str(item.get("gap_id") or "") for item in verification}
    blocked = [
        item for item in mechanism_leads + extraction_shortages
        if isinstance(item, dict) and str(item.get("gap_id") or "") not in verification_ids
    ]
    handoffs: list[dict[str, Any]] = []
    for branch in branches:
        branch_id = normalized_subhypothesis_id(branch.get("id") or branch.get("sub_hypothesis_id"))
        ready = next(
            (item for item in valid if normalized_subhypothesis_id(item.get("sub_hypothesis_id")) == branch_id),
            None,
        )
        lead = next(
            (item for item in blocked if normalized_subhypothesis_id(item.get("sub_hypothesis_id")) == branch_id),
            None,
        )
        verification_lead = next(
            (item for item in verification if normalized_subhypothesis_id(item.get("sub_hypothesis_id")) == branch_id),
            None,
        )
        if ready is not None:
            component_bridge_ready = bool(
                str(ready.get("gap_type") or "") == "component_bridge_gap_synthesis"
                and restricted_component_bridge_role_contract_ready(ready)
            )
            handoffs.append({
                "sub_hypothesis_id": branch_id,
                "focus": str(branch.get("focus") or ""),
                "coverage_status": (
                    "COMPONENT_BRIDGE_GAP_READY"
                    if component_bridge_ready
                    else "SCIENTIFIC_GAP_READY"
                ),
                "gap_id": str(ready.get("gap_id") or ""),
                "gap_track": str(
                    ready.get("gap_track")
                    or (
                        "COMPONENT_BRIDGE_GAP_SYNTHESIS"
                        if component_bridge_ready
                        else ""
                    )
                ),
                "socrates_handoff_allowed": True,
                "socrates_enrichment_required": True,
                "socrates_enrichment_stage": "POST_DRAFT" if component_bridge_ready else "PRE_DRAFT",
                "post_draft_socrates_enrichment_required": component_bridge_ready,
                "next_agent": "mingli" if component_bridge_ready else "socrates",
                "next_action": (
                    "run_mingli_hypothesis_evolution"
                    if component_bridge_ready
                    else "run_socrates_mechanism_evidence_enrichment"
                ),
                "hypothesis_generation_mode": (
                    "RESTRICTED_COMPONENT_BRIDGE_POST_DRAFT_SOCRATES"
                    if component_bridge_ready
                    else ""
                ),
                "eligible_for_final_object_claim": not component_bridge_ready,
                "claim_strength_effect": (
                    "no_final_object_claim_validation"
                    if component_bridge_ready
                    else str(ready.get("claim_strength_effect") or "")
                ),
                "final_object_claim_disclaimer": (
                    "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。"
                    if component_bridge_ready
                    else ""
                ),
                "required_upstream_action": "",
            })
        elif verification_lead is not None:
            handoffs.append({
                "sub_hypothesis_id": branch_id,
                "focus": str(branch.get("focus") or ""),
                "coverage_status": "MECHANISM_VERIFICATION_LEAD_READY",
                "gap_id": str(verification_lead.get("gap_id") or ""),
                "gap_track": "MECHANISM_DISCOVERY_VERIFICATION_LEAD",
                "socrates_handoff_allowed": True,
                "socrates_retrieval_mode": "MECHANISM_VERIFICATION_ONLY",
                "eligible_for_hypothesis_generation": False,
                "may_fill_primary_evidence_slots": False,
                "required_upstream_action": "run_one_bounded_socrates_mechanism_verification",
            })
        elif lead is not None:
            audit = lead.get("scientific_causal_gap_audit") if isinstance(lead.get("scientific_causal_gap_audit"), dict) else {}
            handoffs.append({
                "sub_hypothesis_id": branch_id,
                "focus": str(branch.get("focus") or ""),
                "coverage_status": "BLOCKED_CANDIDATE_REQUIRES_REPAIR",
                "gap_id": "",
                "candidate_ref": str(lead.get("gap_id") or ""),
                "candidate_state": str(lead.get("scientific_state") or lead.get("gap_candidate_pool") or ""),
                "socrates_handoff_allowed": False,
                "required_upstream_action": (
                    "resolve_scientific_entities_or_temporal_evidence"
                    if audit else "repair_source_evidence_extraction"
                ),
                "reason": str(
                    audit.get("reason")
                    or (lead.get("extraction_repair_route") or {}).get("reason")
                    or "The branch has a candidate but not a scientifically admitted gap."
                )[:500],
            })
        else:
            handoffs.append({
                "sub_hypothesis_id": branch_id,
                "focus": str(branch.get("focus") or ""),
                "coverage_status": "NO_VALID_SCIENTIFIC_GAP",
                "gap_id": "",
                "socrates_handoff_allowed": False,
                "required_upstream_action": "return_to_tanxi_or_zhizhi_for_source_bound_gap_evidence",
                "reason": "No source-bound, scientifically coherent, operational gap was established for this branch; no placeholder gap was fabricated.",
            })
    return handoffs

def semantic_plausibility_for_pair(
    project: dict[str, Any],
    method: str,
    scenario: str,
    gap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_scoring import fields_are_incompatible, infer_research_field
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_space, record_context_text
    except ImportError:
        from _literature_scoring import fields_are_incompatible, infer_research_field
        from _pipeline import project_records_for_mapping
        from _utils import normalize_space, record_context_text
    method_text = normalize_space(method).lower()
    scenario_text = normalize_space(scenario).lower()
    project_text = normalize_space(
        " ".join(
            [
                str(project.get("domain", "")),
                str(project.get("objective", "")),
                str((gap or {}).get("description", "")),
                " ".join(record_context_text(record) for record in project_records_for_mapping(project)[:20]),
            ]
        )
    ).lower()
    requirements = method_input_requirements(method_text)
    affordances = scenario_data_affordances(f"{scenario_text} {project_text}")
    bridge = semantic_bridge_terms(method_text, scenario_text, project_text)
    score = 0.45
    score_breakdown: list[dict[str, Any]] = [{"factor": "base_prior", "delta": 0.45, "reason": "default prior before evidence checks"}]
    reasons: list[str] = []

    if concepts_are_connected(project, method, scenario):
        score += 0.35
        score_breakdown.append({"factor": "papergraph_cooccurrence", "delta": 0.35, "reason": "method and scenario co-occur in PaperGraph"})
        reasons.append("method and scenario already co-occur in at least one PaperGraph record")
    if bridge:
        delta = min(0.3, 0.08 * len(bridge))
        score += delta
        score_breakdown.append({"factor": "bridge_terms", "delta": round(delta, 3), "reason": f"{len(bridge)} bridge concept(s) detected"})
        reasons.append(f"bridge concepts detected: {', '.join(bridge[:6])}")
    if requirements:
        missing = sorted(requirements - affordances)
        if missing:
            delta = -min(0.5, 0.18 * len(missing))
            score += delta
            score_breakdown.append({"factor": "missing_method_affordances", "delta": round(delta, 3), "reason": ", ".join(missing)})
            reasons.append(f"method input requirements not visible in scenario/context: {', '.join(missing)}")
        else:
            score += 0.2
            score_breakdown.append({"factor": "matched_method_affordances", "delta": 0.2, "reason": "scenario/context exposes required data affordances"})
            reasons.append("scenario/context exposes the required data affordances")

    method_field = infer_research_field({"title": method, "abstract": method})
    scenario_field = infer_research_field({"title": scenario, "abstract": f"{scenario} {project.get('domain', '')}"})
    field_incompatible = fields_are_incompatible(method_field, scenario_field)
    pair_connected = concepts_are_connected(project, method, scenario)
    cross_domain_distance = (
        1.0 if field_incompatible and not bridge and not pair_connected
        else 0.55 if method_field and scenario_field and method_field != scenario_field and not bridge
        else 0.0
    )
    if field_incompatible and not bridge and not pair_connected:
        delta = -0.35 if not project_context_mentions_pair(project_text, method_text, scenario_text) else -0.25
        score += delta
        score_breakdown.append({"factor": "field_mismatch_without_bridge", "delta": round(delta, 3), "reason": f"{method_field} -> {scenario_field}"})
        reasons.append(f"field mismatch without bridge evidence: {method_field} -> {scenario_field}")

    if ambiguous_short_method_label(method) and not bridge and not concepts_are_connected(project, method, scenario):
        score -= 0.2
        score_breakdown.append({"factor": "ambiguous_short_label_without_bridge", "delta": -0.2, "reason": "short acronym-like method label has no explicit bridge in context"})
        reasons.append("short acronym-like method label may be ambiguous across disciplines and lacks bridge evidence")

    if migration_noise_risk(project_text, method_text, scenario_text, bridge):
        score -= 0.2
        score_breakdown.append({"factor": "migration_noise_risk", "delta": -0.2, "reason": "pair appears to be driven by disconnected source domains rather than a shared mechanism"})
        reasons.append("cross-domain transfer risk: no shared mechanism terms, project context, or PaperGraph bridge")

    if method_looks_like_narrow_tool(method_text) and not ({"spatial_coordinates", "spatial_context"} & affordances):
        score -= 0.3
        score_breakdown.append({"factor": "narrow_tool_modality_mismatch", "delta": -0.3, "reason": "tool implies a data modality absent from scenario/context"})
        reasons.append("narrow tool/software method appears without matching data modality in the scenario")

    score = round(max(0.0, min(1.0, score)), 3)
    if cross_domain_distance >= 0.8:
        verdict = "REJECT"
    elif score < 0.32:
        verdict = "REJECT"
    elif score < 0.55:
        verdict = "HUMAN_REVIEW"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "score": score,
        "requirements": sorted(requirements),
        "scenario_affordances": sorted(affordances),
        "bridge_terms": bridge[:10],
        "method_field": method_field,
        "scenario_field": scenario_field,
        "cross_domain_distance": cross_domain_distance,
        "cross_domain_risk": "HIGH" if cross_domain_distance >= 0.8 else "MEDIUM" if cross_domain_distance >= 0.5 else "LOW",
        "score_breakdown": score_breakdown,
        "reason": "; ".join(reasons) if reasons else "no obvious semantic incompatibility detected",
    }

def method_input_requirements(method_text: str) -> set[str]:
    rules: list[tuple[tuple[str, ...], set[str]]] = [
        (("kernel density", "kde", "arcgis", "gis", "geospatial", "spatial interpolation", "hotspot analysis"), {"spatial_coordinates"}),
        (("cnn", "convolution", "vision transformer", "image segmentation", "microscopy"), {"image"}),
        (("lstm", "rnn", "recurrent", "sequence model", "time series", "temporal"), {"sequence"}),
        (("graph neural", "gnn", "message passing", "network embedding", "knowledge graph"), {"graph"}),
        (("single-cell", "scrna", "transcriptomic", "omics", "proteomic", "multi-omics"), {"omics"}),
        (("causal", "counterfactual", "instrumental variable", "difference-in-differences"), {"intervention"}),
        (("molecular docking", "density functional", "dft", "quantum", "molecular dynamics"), {"molecular"}),
    ]
    reqs: set[str] = set()
    for terms, required in rules:
        if any(term in method_text for term in terms):
            reqs.update(required)
    return reqs

def scenario_data_affordances(text: str) -> set[str]:
    rules: list[tuple[tuple[str, ...], str]] = [
        (("spatial transcriptomics", "spatial proteomics", "coordinate", "coordinates", "geospatial", "location", "neighborhood map"), "spatial_coordinates"),
        (("spatial", "atlas", "map", "mapping", "histology", "microenvironment", "neighborhood", "local context"), "spatial_context"),
        (("image", "imaging", "microscopy", "histology", "radiology", "pathology slide", "scan"), "image"),
        (("time", "temporal", "longitudinal", "trajectory", "dynamic", "persistence", "survival", "progression"), "sequence"),
        (("interaction", "network", "pathway", "graph", "cell-cell", "protein-protein", "ppi", "signaling"), "graph"),
        (("omics", "transcript", "rna-seq", "single-cell", "scrna", "proteomic", "genomic", "expression", "atlas"), "omics"),
        (("intervention", "trial", "randomized", "knockout", "perturbation", "dose", "treatment", "causal"), "intervention"),
        (("molecule", "protein", "ligand", "binding", "structure", "receptor", "site", "motif"), "molecular"),
    ]
    affordances: set[str] = set()
    for terms, affordance in rules:
        if any(term in text for term in terms):
            affordances.add(affordance)
    return affordances

def semantic_bridge_terms(method_text: str, scenario_text: str, project_text: str) -> list[str]:
    bridges = [
        "spatially resolved measurement",
        "reference atlas",
        "single-cell atlas",
        "context map",
        "interaction network",
        "heterogeneity profile",
        "target specificity",
        "adverse-effect profile",
        "multi-omics",
        "multi-modal measurement",
        "mechanistic model",
        "causal pathway",
        "benchmark dataset",
        "simulation",
        "domain adaptation",
        "boundary condition",
        "stress test",
    ]
    text = f"{method_text} {scenario_text} {project_text}"
    return [term for term in bridges if term in text]

def method_looks_like_narrow_tool(method_text: str) -> bool:
    return any(term in method_text for term in ("arcgis", "qgis", "gis", "kernel density", "kde", "excel", "tableau"))

def ambiguous_short_method_label(method: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    raw = normalize_space(str(method or ""))
    compact = re.sub(r"[^A-Za-z0-9]", "", raw)
    if 2 <= len(compact) <= 5 and compact.upper() == compact and any(ch.isalpha() for ch in compact):
        return True
    words = raw.split()
    if len(words) > 1:
        return False
    return 2 <= len(raw) <= 5 and raw.lower() in {"ai", "ml", "rl", "md", "sem", "mas", "pde", "ode", "gcn", "vae"}

def project_context_mentions_pair(project_text: str, method_text: str, scenario_text: str) -> bool:
    try:
        from ._literature_search import query_terms
        from ._utils import science_term_in_text
    except ImportError:
        from _literature_search import query_terms
        from _utils import science_term_in_text
    method_terms = set(query_terms(method_text))
    scenario_terms = set(query_terms(scenario_text))
    if not method_terms or not scenario_terms:
        return False
    method_hit = any(science_term_in_text(term, project_text) for term in method_terms)
    scenario_hit = any(science_term_in_text(term, project_text) for term in scenario_terms)
    return method_hit and scenario_hit

def migration_noise_risk(project_text: str, method_text: str, scenario_text: str, bridge: list[str]) -> bool:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    if bridge:
        return False
    method_terms = set(query_terms(method_text))
    scenario_terms = set(query_terms(scenario_text))
    project_terms = set(query_terms(project_text))
    if not method_terms or not scenario_terms:
        return True
    shared = method_terms & scenario_terms
    method_overlap = method_terms & project_terms
    scenario_overlap = scenario_terms & project_terms
    return not shared and (not method_overlap or not scenario_overlap)

def count_gap_type(gaps: list[dict[str, Any]], gap_type: str) -> int:
    return sum(1 for gap in gaps if gap.get("gap_type") == gap_type)


def _normalized_causal_identity_value(value: Any) -> str:
    """Normalize one causal field without imposing a domain vocabulary."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"[^a-z0-9\u0370-\u03ff\u4e00-\u9fff_+./\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def causal_gap_identity(gap: dict[str, Any]) -> dict[str, Any]:
    """Return the source-bound causal identity used for post-bundle dedupe."""
    bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    chain = bundle.get("causal_chain") if isinstance(bundle.get("causal_chain"), dict) else {}
    causal_verdict = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    verdict_fields = causal_verdict.get("causal_fields") if isinstance(causal_verdict.get("causal_fields"), dict) else {}
    seed_contract = (
        gap.get("mechanism_seed_contract")
        if isinstance(gap.get("mechanism_seed_contract"), dict)
        else bundle.get("mechanism_seed_contract")
        if isinstance(bundle.get("mechanism_seed_contract"), dict)
        else {}
    )
    mechanism_seed = (
        seed_contract.get("mechanism_seed")
        if isinstance(seed_contract.get("mechanism_seed"), dict)
        else {}
    )

    def seed_value(field: str) -> str:
        entry = mechanism_seed.get(field) if isinstance(mechanism_seed.get(field), dict) else {}
        normalized = _normalized_causal_identity_value(entry.get("value"))
        if normalized and normalized not in {"unresolved", "unknown", "none", "n/a"}:
            return normalized
        return ""

    def chain_value(field: str) -> str:
        entry = chain.get(field) if isinstance(chain.get(field), dict) else {}
        candidates = [entry.get("value"), entry.get("candidate"), seed_value(field)]
        for candidate in candidates:
            normalized = _normalized_causal_identity_value(candidate)
            if normalized and normalized not in {"unresolved", "unknown", "none", "n/a"}:
                return normalized
        return "unresolved"

    source_ids: set[str] = set()
    source_verdict = gap.get("source_alignment_verdict") if isinstance(gap.get("source_alignment_verdict"), dict) else {}
    for item in source_verdict.get("source_roles", []) or []:
        if isinstance(item, dict) and str(item.get("paper_id") or "").strip():
            source_ids.add(str(item.get("paper_id")).strip())
    for item in bundle.get("mechanism_source_spans", []) or []:
        if isinstance(item, dict) and str(item.get("paper_id") or "").strip():
            source_ids.add(str(item.get("paper_id")).strip())
    for item in bundle.get("gap_anchor_fragment_alignments", []) or []:
        if isinstance(item, dict) and str(item.get("paper_id") or "").strip():
            source_ids.add(str(item.get("paper_id")).strip())
    if not source_ids:
        source_ids.update(
            str(item).strip()
            for item in (bundle.get("matched_gap_signal_record_ids") or [])
            if str(item).strip()
        )
    identity = {
        "sub_hypothesis_id": _normalized_causal_identity_value(
            bundle.get("sub_hypothesis_id") or gap.get("sub_hypothesis_id")
        ),
        "source_paper_ids": sorted(source_ids),
        "input": _normalized_causal_identity_value(
            ((verdict_fields.get("input") or {}).get("value") if isinstance(verdict_fields.get("input"), dict) else "")
        ) or chain_value("input"),
        "mediator": _normalized_causal_identity_value(
            ((verdict_fields.get("mediator") or {}).get("value") if isinstance(verdict_fields.get("mediator"), dict) else "")
            or " | ".join(str(item) for item in (verdict_fields.get("competing_mechanisms") or []) if str(item).strip())
        ) or chain_value("mediator"),
        "outcome": _normalized_causal_identity_value(
            ((verdict_fields.get("outcome") or {}).get("value") if isinstance(verdict_fields.get("outcome"), dict) else "")
        ) or chain_value("outcome"),
        "research_mode": _normalized_causal_identity_value(
            causal_verdict.get("research_mode") or bundle.get("research_mode") or gap.get("research_mode") or "UNRESOLVED_RESEARCH_DESIGN"
        ),
    }
    # Do not collapse pre-bundle narrative candidates just because every
    # causal field is unresolved.  They still need independent semantic audit.
    identity["eligible_for_dedupe"] = bool(
        identity["sub_hypothesis_id"]
        and identity["source_paper_ids"]
        and sum(
            identity[field] != "unresolved"
            for field in ("input", "mediator", "outcome")
        ) >= 2
    )
    identity["key"] = json.dumps(
        {key: value for key, value in identity.items() if key not in {"key", "eligible_for_dedupe"}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return identity


def dedupe_causal_identity_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only gaps that represent the same source-bound causal object."""
    deduped: list[dict[str, Any]] = []
    by_identity: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        identity = causal_gap_identity(gap)
        gap["causal_identity"] = identity
        key = str(identity.get("key") or "")
        if not identity.get("eligible_for_dedupe") or key not in by_identity:
            deduped.append(gap)
            if identity.get("eligible_for_dedupe"):
                by_identity[key] = gap
            continue
        representative = by_identity[key]
        aliases = [
            str(value).strip()
            for value in (
                list(representative.get("merged_gap_ids") or [])
                + [representative.get("gap_id")]
                + list(gap.get("merged_gap_ids") or [])
                + [gap.get("gap_id")]
            )
            if str(value or "").strip()
        ]
        representative["merged_gap_ids"] = list(dict.fromkeys(aliases))
        refs = [
            str(value).strip()
            for value in (
                list(representative.get("supporting_references") or [])
                + list(gap.get("supporting_references") or [])
            )
            if str(value or "").strip()
        ]
        representative["supporting_references"] = list(dict.fromkeys(refs))[:16]
        representative["deduped_from"] = int(representative.get("deduped_from") or 0) + 1
    return deduped

def dedupe_knowledge_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    deduped: list[dict[str, Any]] = []
    for gap in gaps:
        description = str(gap.get("description", ""))
        signature = gap_signature(description)
        duplicate = None
        for existing in deduped:
            existing_description = str(existing.get("description", ""))
            if signature and signature == gap_signature(existing_description):
                duplicate = existing
                break
            if gap_signature_is_subset(signature, gap_signature(existing_description)):
                duplicate = existing
                break
            if text_jaccard(description, existing_description) >= 0.72:
                duplicate = existing
                break
        if duplicate is not None:
            merged_refs = unique_preserve_order(
                list(duplicate.get("supporting_references", [])) + list(gap.get("supporting_references", []))
            )
            duplicate["supporting_references"] = merged_refs[:8]
            source_units = [
                item for item in (
                    list(duplicate.get("source_evidence_units") or [])
                    + list(gap.get("source_evidence_units") or [])
                )
                if isinstance(item, dict) and item.get("paper_id") and item.get("source_unit_id")
            ]
            by_source_unit = {
                (str(item.get("paper_id")), str(item.get("source_unit_id"))): item
                for item in source_units
            }
            if by_source_unit:
                duplicate["source_evidence_units"] = list(by_source_unit.values())[:16]
            pool_priority = {
                PRIMARY_MECHANISM_CANDIDATE_POOL: 3,
                COMPOSITE_GAP_AUDIT_POOL: 2,
                SECONDARY_RESEARCH_OPPORTUNITY_POOL: 1,
                EVIDENCE_EXTRACTION_SHORTAGE_POOL: 0,
            }
            duplicate_pool = str(duplicate.get("gap_candidate_pool") or default_gap_candidate_pool(str(duplicate.get("gap_type") or "")))
            incoming_pool = str(gap.get("gap_candidate_pool") or default_gap_candidate_pool(str(gap.get("gap_type") or "")))
            if pool_priority.get(incoming_pool, 0) > pool_priority.get(duplicate_pool, 0):
                duplicate["gap_candidate_pool"] = incoming_pool
                duplicate["gap_type"] = gap.get("gap_type")
                for semantic_key in (
                    "gap_signal", "mechanism_issue_signal", "reasoning_signal", "causal_gap",
                    "causal_mediation", "gap_epistemic_audit", "sub_hypothesis_id",
                ):
                    if gap.get(semantic_key) not in (None, "", [], {}):
                        duplicate[semantic_key] = gap.get(semantic_key)
            duplicate.setdefault("discovery_aliases", []).append({
                "gap_id": str(gap.get("gap_id") or ""),
                "gap_type": str(gap.get("gap_type") or ""),
                "gap_candidate_pool": str(gap.get("gap_candidate_pool") or ""),
            })
            duplicate["deduped_from"] = duplicate.get("deduped_from", 0) + 1
            if int(gap.get("novelty_score", 0)) > int(duplicate.get("novelty_score", 0)):
                duplicate.update({key: gap[key] for key in ("novelty_score", "application_value", "feasibility") if key in gap})
            continue
        gap["dedupe_signature"] = signature
        deduped.append(gap)
    return deduped

def filter_low_value_gaps(gaps: list[dict[str, Any]], min_novelty: int = 4) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for gap in gaps:
        novelty = int(gap.get("novelty_score") or 0)
        if novelty >= min_novelty:
            kept.append(gap)
            continue
        item = {
            "gap_id": gap.get("gap_id"),
            "gap_type": gap.get("gap_type"),
            "novelty_score": novelty,
            "description": trim_text(str(gap.get("description", "")), 220),
            "reason": f"novelty_score below reporting threshold {min_novelty}",
            "assessment_reason": gap.get("assessment_reason", ""),
            "novelty_score_breakdown": gap.get("novelty_score_breakdown", {}),
            "evidence_grounding_score": gap.get("evidence_grounding_score"),
            "source_text_overlap": gap.get("source_text_overlap"),
            "independent_resolution_overlap": gap.get("strongest_independent_resolution_overlap"),
            "independent_resolution_evidence": (
                (gap.get("evidence_grounding") or {}).get("independent_resolution_evidence", [])
                if isinstance(gap.get("evidence_grounding"), dict)
                else []
            ),
        }
        rejected.append(item)
    return kept, rejected

def gap_signature(description: str) -> str:
    stop = {
        "method",
        "scenario",
        "recorded",
        "validation",
        "current",
        "papergraph",
        "map",
        "source",
        "literature",
        "indicates",
        "has",
        "have",
        "against",
        "worth",
        "testing",
        "unresolved",
        "problem",
    }
    terms = [
        term
        for term in re.findall(r"[a-z0-9][a-z0-9_-]*", description.lower())
        if term not in stop
    ]
    return " ".join(sorted(terms[:10]))

def gap_signature_is_subset(left: str, right: str) -> bool:
    left_terms = set(left.split())
    right_terms = set(right.split())
    if not left_terms or not right_terms:
        return False
    smaller, larger = (left_terms, right_terms) if len(left_terms) <= len(right_terms) else (right_terms, left_terms)
    return len(smaller) >= 3 and smaller.issubset(larger)

def text_jaccard(left: str, right: str) -> float:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    left_terms = set(query_terms(left))
    right_terms = set(query_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)

def parse_gap_input(gap: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(gap, dict):
        return dict(gap)
    text = str(gap)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return make_gap(
        gap_type="problem",
        description=text,
        supporting_references=[],
        suggested_research_path="Run a focused literature overlap check, then design a minimal validation protocol.",
        value_argument="Value is unknown until novelty and feasibility are assessed.",
    )

GAP_RESOLUTION_MARKERS = (
    "we demonstrate",
    "we establish",
    "we identify",
    "we resolve",
    "we show that",
    "we find that",
    "reveals that",
    "demonstrates that",
    "establishes that",
    "is necessary for",
    "is sufficient for",
    "causal role",
    "mechanism is mediated by",
    "validated by",
)

GAP_UNRESOLVED_MARKERS = (
    "remains unclear",
    "remains unknown",
    "remains unresolved",
    "not fully understood",
    "poorly understood",
    "insufficiently explored",
    "future work",
    "further research",
    "limitation",
    "challenge",
    "open question",
    "lack of evidence",
    "missing evidence",
)

GAP_SCORING_SCAFFOLD_TERMS = frozenset(
    {
        "source-grounded",
        "source",
        "grounded",
        "mechanism",
        "gap",
        "method",
        "scenario",
        "benchmark",
        "problem",
        "issue",
        "reported",
        "literature",
        "current",
        "papergraph",
        "remains",
    }
)


def normalized_gap_reference(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def record_matches_gap_reference(record: dict[str, Any], references: list[str]) -> bool:
    normalized_refs = [normalized_gap_reference(ref) for ref in references if normalized_gap_reference(ref)]
    if not normalized_refs:
        return False
    candidates = [
        str(record.get(field) or "")
        for field in ("citation", "title", "doi", "arxiv_id", "semantic_scholar_id", "url", "paper_id")
    ]
    normalized_candidates = [normalized_gap_reference(value) for value in candidates if normalized_gap_reference(value)]
    for reference in normalized_refs:
        for candidate in normalized_candidates:
            if reference == candidate:
                return True
            # Citations normally contain the complete paper title or identifier.
            if len(candidate) >= 16 and candidate in reference:
                return True
            if len(reference) >= 16 and reference in candidate:
                return True
    return False


def gap_source_signal(gap: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "mechanism_issue_signal",
        "gap_signal",
        "reasoning_signal",
        "causal_gap",
        "causal_mediation",
        "cross_hypothesis_synthesis",
    ):
        value = gap.get(field)
        if isinstance(value, dict) and value:
            return {"field": field, "payload": value}
    return {"field": "", "payload": {}}


def gap_core_scoring_text(gap: dict[str, Any]) -> str:
    signal = gap_source_signal(gap).get("payload") or {}
    signal_text = " ".join(
        str(signal.get(field) or "")
        for field in ("source_text", "text", "unknown", "missing_kind", "evidence_needed")
        if signal.get(field)
    ).strip()
    return signal_text or str(gap.get("description") or "")


def gap_resolution_and_grounding_assessment(
    project: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    """Separate evidence grounding from evidence that independently closes a gap.

    A source paper quoted by a limitation/open-problem gap is positive grounding;
    it must never be treated as a prior solution merely because the text overlaps.
    Only a different record with overlapping concepts and affirmative resolution
    language contributes to the novelty penalty.
    """
    try:
        from ._literature_search import query_terms
        from ._pipeline import project_records_for_mapping
        from ._utils import record_context_text
    except ImportError:
        from _literature_search import query_terms
        from _pipeline import project_records_for_mapping
        from _utils import record_context_text

    references = [str(ref) for ref in gap.get("supporting_references", []) if str(ref).strip()]
    core_terms = {
        term
        for term in query_terms(gap_core_scoring_text(gap))
        if term not in GAP_SCORING_SCAFFOLD_TERMS
    }
    source_matches: list[dict[str, Any]] = []
    independent_topic_matches: list[dict[str, Any]] = []
    independent_resolution: list[dict[str, Any]] = []
    records = [record for record in project_records_for_mapping(project) if isinstance(record, dict)]
    for record in records:
        record_terms = set(query_terms(record_context_text(record)))
        overlap = len(core_terms & record_terms) / max(1, len(core_terms)) if core_terms else 0.0
        match = {
            "paper_id": record.get("paper_id"),
            "title": record.get("title", ""),
            "citation": record_reference(record),
            "overlap_score": round(overlap, 4),
            "matched_terms": sorted(core_terms & record_terms)[:12],
        }
        if record_matches_gap_reference(record, references):
            source_matches.append(match)
            continue
        if overlap <= 0:
            continue
        independent_topic_matches.append(match)
        resolution_text = " ".join(
            str(record.get(field) or "")
            for field in ("contribution", "conclusion", "strengths")
        ).lower()
        limitation_text = " ".join(
            str(record.get(field) or "")
            for field in ("limitation", "improvements")
        ).lower()
        resolution_markers = [marker for marker in GAP_RESOLUTION_MARKERS if marker in resolution_text]
        unresolved_markers = [
            marker
            for marker in GAP_UNRESOLVED_MARKERS
            if marker in resolution_text or marker in limitation_text
        ]
        if overlap >= 0.35 and resolution_markers and not unresolved_markers:
            independent_resolution.append(
                {
                    **match,
                    "resolution_markers": resolution_markers[:5],
                }
            )

    source_matches.sort(key=lambda item: -float(item.get("overlap_score") or 0.0))
    independent_topic_matches.sort(key=lambda item: -float(item.get("overlap_score") or 0.0))
    independent_resolution.sort(key=lambda item: -float(item.get("overlap_score") or 0.0))
    signal = gap_source_signal(gap)
    matched_reference_fraction = min(1.0, len(source_matches) / max(1, len(references))) if references else 0.0
    source_overlap = max((float(item["overlap_score"]) for item in source_matches), default=0.0)
    grounding_score = min(
        1.0,
        0.45 * matched_reference_fraction
        + 0.25 * (1.0 if signal.get("field") else 0.0)
        + 0.20 * source_overlap
        + 0.10 * (1.0 if references else 0.0),
    )
    strongest_resolution_overlap = max(
        (float(item["overlap_score"]) for item in independent_resolution),
        default=0.0,
    )
    return {
        "evidence_grounding_score": round(grounding_score, 4),
        "supporting_reference_count": len(references),
        "matched_supporting_source_count": len(source_matches),
        "source_text_overlap": round(source_overlap, 4),
        "source_signal_field": str(signal.get("field") or ""),
        "independent_topic_overlap": max(
            (float(item["overlap_score"]) for item in independent_topic_matches),
            default=0.0,
        ),
        "independent_resolution_overlap": round(strongest_resolution_overlap, 4),
        "independent_resolution_source_count": len(independent_resolution),
        "independent_resolution_evidence": independent_resolution[:5],
        "supporting_source_matches": source_matches[:5],
    }


def scientific_gap_scoring_eligibility(gap: dict[str, Any]) -> dict[str, Any]:
    """Decide whether novelty/value scores describe a real gap predicate."""

    epistemic = gap.get("gap_epistemic_verdict") if isinstance(gap.get("gap_epistemic_verdict"), dict) else {}
    anomaly_evidence = (
        gap.get("anomaly_evidence_sufficiency")
        if isinstance(gap.get("anomaly_evidence_sufficiency"), dict) else {}
    )
    if anomaly_evidence.get("requires_independent_corroboration") is True:
        return {
            "eligible": False,
            "status": "ANOMALY_CORROBORATION_REQUIRED",
            "reason": str(anomaly_evidence.get("reason") or "Independent anomaly corroboration is missing."),
        }
    if epistemic:
        return {
            "eligible": epistemic.get("passes") is True,
            "status": str(epistemic.get("verdict") or "UNRESOLVED"),
            "reason": str(epistemic.get("reason") or ""),
        }
    composite = gap.get("composite_evidence_contract") if isinstance(gap.get("composite_evidence_contract"), dict) else {}
    if composite.get("status") == "PASSED":
        return {
            "eligible": True,
            "status": "COMPOSITE_CONTRACT_PASSED",
            "reason": "A paper-qualified composite gap contract passed.",
        }
    audit = gap.get("gap_epistemic_audit") if isinstance(gap.get("gap_epistemic_audit"), dict) else {}
    source_signal = gap_source_signal(gap).get("payload") or {}
    source_text = str(
        source_signal.get("source_text") or source_signal.get("text")
        or " ".join(
            str(item.get("excerpt") or "")
            for item in (gap.get("source_evidence_units") or [])
            if isinstance(item, dict)
        )
    )
    predicate = explicit_gap_predicate_assessment(source_text)
    eligible = bool(audit.get("passes") and predicate.get("passes"))
    return {
        "eligible": eligible,
        "status": "EXPLICIT_GAP_PREDICATE" if eligible else "NO_GAP_PREDICATE",
        "reason": (
            "A source-bound missing-knowledge predicate is present."
            if eligible else "No source-bound problem, contradiction, unknown, failure, or missing-knowledge predicate was established."
        ),
        "explicit_predicate_assessment": predicate,
    }


def scientific_gap_value_attribution(gap: dict[str, Any]) -> dict[str, Any]:
    """Assign value to resolving a gap, never to an observed capability itself."""

    scoring = scientific_gap_scoring_eligibility(gap)
    description = str(gap.get("description") or gap.get("gap_description") or "")
    resolution_text = " ".join(
        str(gap.get(field) or "")
        for field in ("value_argument", "suggested_research_path", "recommended_approach")
    ).lower()
    observed_text = description.lower()
    positive_performance = any(marker in observed_text for marker in _POSITIVE_PERFORMANCE_MARKERS)
    high_resolution_impact = any(
        marker in resolution_text
        for marker in (
            "safety", "mortality", "clinical outcome", "catastrophic", "toxicity", "failure boundary",
            "large-scale", "scalability", "energy efficiency", "environmental risk", "public health",
        )
    )
    if not scoring.get("eligible"):
        potential_resolution_value = "unassessed"
        application_value = "low"
        basis = "No scientific gap predicate exists, so application value cannot be assigned to this candidate as a gap."
    else:
        potential_resolution_value = "high" if high_resolution_impact else "medium"
        application_value = potential_resolution_value
        basis = "Application value is the prospective benefit of explaining, bounding, or resolving the admitted gap."
    reasoning_signal = gap.get("reasoning_signal") if isinstance(gap.get("reasoning_signal"), dict) else {}
    resolution_target = str(reasoning_signal.get("resolution_target") or "") or (
        "EXPLANATORY_MECHANISM_OR_FAILURE_BOUNDARY"
        if str(gap.get("gap_type") or "") == "anomaly" else "SOURCE_STATED_GAP_RESOLUTION"
    )
    return {
        "version": "scientific_gap_value_attribution_v1",
        "scoring_eligible": scoring.get("eligible") is True,
        "gap_status": str(scoring.get("status") or "UNRESOLVED"),
        "current_observation_kind": (
            "POSITIVE_PERFORMANCE_OR_CAPABILITY_CLAIM" if positive_performance else "SCIENTIFIC_PROBLEM_OR_UNKNOWN_CANDIDATE"
        ),
        "current_observation_application_value": "NOT_SCORED_AS_GAP_VALUE",
        "resolution_target": resolution_target,
        "potential_resolution_value": potential_resolution_value,
        "application_value": application_value,
        "value_belongs_to": "POTENTIAL_BENEFIT_IF_GAP_IS_RESOLVED" if scoring.get("eligible") else "NO_GAP_VALUE_ASSIGNED",
        "basis": basis,
        "eligibility": scoring,
    }


def assess_gap_dict(project: dict[str, Any], gap: dict[str, Any], dimensions: list[str] | None = None) -> dict[str, Any]:
    assessed = dict(gap)
    refs = [ref for ref in assessed.get("supporting_references", []) if ref]
    description = str(assessed.get("description", ""))
    gap_type = str(assessed.get("gap_type", ""))
    topic_density = literature_coverage_factor(project, description)
    evidence_assessment = gap_resolution_and_grounding_assessment(project, assessed)
    value_attribution = scientific_gap_value_attribution(assessed)
    scoring_eligible = value_attribution.get("scoring_eligible") is True
    resolution_overlap = float(evidence_assessment.get("independent_resolution_overlap") or 0.0)
    resolution_sources = int(evidence_assessment.get("independent_resolution_source_count") or 0)
    novelty = 5
    novelty_adjustments: list[dict[str, Any]] = []
    if scoring_eligible and gap_type in EVIDENCE_DERIVED_GAP_GENERATOR_TYPES:
        novelty += 1
        novelty_adjustments.append({"reason": "evidence_derived_candidate_type", "delta": 1})
    if scoring_eligible and evidence_assessment.get("source_signal_field"):
        novelty += 1
        novelty_adjustments.append({"reason": "source_located_gap_signal", "delta": 1})
    if scoring_eligible and gap_type in {"contradiction", "anomaly", "theory_observation_mismatch"}:
        novelty += 1
        novelty_adjustments.append({"reason": "independent_tension_or_anomaly", "delta": 1})

    # Topic density is reported for context but does not imply that the gap has
    # been solved. Novelty is reduced only by independent affirmative evidence
    # that overlaps the proposed missing relation.
    if resolution_overlap >= 0.65 and resolution_sources >= 2:
        novelty -= 4
        novelty_adjustments.append({"reason": "multiple_independent_resolution_sources", "delta": -4})
    elif resolution_overlap >= 0.65:
        novelty -= 3
        novelty_adjustments.append({"reason": "strong_independent_resolution_evidence", "delta": -3})
    elif resolution_overlap >= 0.50:
        novelty -= 2
        novelty_adjustments.append({"reason": "moderate_independent_resolution_evidence", "delta": -2})
    if not refs:
        novelty -= 1
        novelty_adjustments.append({"reason": "missing_supporting_reference", "delta": -1})
    if not scoring_eligible:
        pre_cap_novelty = novelty
        novelty = min(novelty, 3)
        novelty_adjustments.append({
            "reason": "no_admitted_scientific_gap_score_cap",
            "delta": novelty - pre_cap_novelty,
            "cap": 3,
        })
    semantic_gate = assessed.get("semantic_plausibility") if isinstance(assessed.get("semantic_plausibility"), dict) else {}
    if semantic_gate.get("verdict") == "HUMAN_REVIEW":
        novelty -= 1
        novelty_adjustments.append({"reason": "semantic_context_requires_review", "delta": -1})
    elif semantic_gate.get("verdict") == "REJECT":
        novelty -= 4
        novelty_adjustments.append({"reason": "semantic_context_rejected", "delta": -4})
    novelty = max(1, min(10, novelty))
    feasibility = "high" if refs and gap_type in {"improvement", "mechanism_problem", "combinatorial", "contradiction", "anomaly"} else "medium"
    if semantic_gate.get("verdict") == "HUMAN_REVIEW":
        feasibility = "low"
    elif semantic_gate.get("verdict") == "REJECT":
        feasibility = "low"
    if any(term in description.lower() for term in ("large-scale", "clinical", "expensive", "proprietary", "closed-source")):
        feasibility = "low"
    application_value = str(value_attribution.get("application_value") or "low")
    assessed.update(
        {
            "novelty_score": novelty,
            "application_value": application_value,
            "potential_resolution_value": str(value_attribution.get("potential_resolution_value") or "unassessed"),
            "value_attribution": value_attribution,
            "gap_scoring_eligible": scoring_eligible,
            "feasibility": feasibility,
            "assessment_dimensions": dimensions or [
                "scientific gap existence", "academic novelty", "potential value if resolved", "implementation feasibility",
            ],
            "evidence_grounding_score": evidence_assessment["evidence_grounding_score"],
            "evidence_grounding": evidence_assessment,
            "overlap_risk": "high" if resolution_overlap >= 0.65 else "medium" if resolution_overlap >= 0.50 else "low",
            # Backward-compatible key now means overlap with an independent
            # resolution source, not overlap with the cited source itself.
            "strongest_overlap": resolution_overlap,
            "strongest_independent_resolution_overlap": resolution_overlap,
            "source_text_overlap": evidence_assessment["source_text_overlap"],
            "literature_coverage_factor": topic_density,
            "topic_density": topic_density,
            "novelty_score_breakdown": {
                "base": 5,
                "adjustments": novelty_adjustments,
                "final": novelty,
                "independent_resolution_source_count": resolution_sources,
                "independent_resolution_overlap": resolution_overlap,
                "topic_density_not_used_as_penalty": topic_density,
            },
            "assessment_reason": (
                f"refs={len(refs)}, gap_type={gap_type}, grounding={evidence_assessment['evidence_grounding_score']}, "
                f"source_overlap={evidence_assessment['source_text_overlap']}, "
                f"independent_resolution_overlap={round(resolution_overlap, 3)}, "
                f"independent_resolution_sources={resolution_sources}, topic_density={round(topic_density, 3)}, "
                f"feasibility={feasibility}, application_value={application_value}, "
                f"semantic_plausibility={semantic_gate.get('verdict', 'not_run')}"
            ),
            "requires_human_review": (
                resolution_overlap >= 0.65
                or not refs
                or semantic_gate.get("verdict") in {"HUMAN_REVIEW", "REJECT"}
            ),
        }
    )
    return assessed

def detect_migration_gaps(project: dict[str, Any], methods: list[str], scenarios: list[str], limit: int) -> list[dict[str, Any]]:
    try:
        from ._pipeline import supporting_references_for_method_or_scenario
    except ImportError:
        from _pipeline import supporting_references_for_method_or_scenario
    gaps: list[dict[str, Any]] = []
    matrix: dict[str, dict[str, list[str]]] = project.get("coverage_matrix", {})
    for method in methods:
        covered = set(matrix.get(method, {}))
        if len(covered) != 1:
            continue
        missing = [scenario for scenario in scenarios if scenario not in covered]
        if not missing:
            continue
        source = next(iter(covered))
        refs = supporting_references_for_method_or_scenario(project, method, source)
        gap = make_gap(
            gap_type="migration",
            description=f"Method '{method}' is only recorded in scenario '{source}', but may be transferable to scenario '{missing[0]}'.",
            supporting_references=refs,
            suggested_research_path="Audit assumptions of the source scenario, then run a small transfer validation in the target scenario.",
            value_argument="Migration gaps can create useful cross-domain leverage if mechanism assumptions remain valid.",
        )
        gate = semantic_plausibility_for_pair(project, method, missing[0], gap)
        gap["semantic_plausibility"] = gate
        if gate.get("verdict") == "REJECT":
            continue
        gaps.append(assess_gap_dict(project, gap))
        if len(gaps) >= limit:
            break
    return gaps

def detect_gap_signal_gaps(project: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import is_unknown_value, normalize_label, unique_preserve_order
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import is_unknown_value, normalize_label, unique_preserve_order
    gaps: list[dict[str, Any]] = []
    records, _ = admitted_method_scenario_benchmark_records(
        project_records_for_mapping(project),
        allow_noncore_context=True,
    )
    # Source-bound causal gap signals are paper-level evidence, not necessarily
    # method-scenario-benchmark triples.  Do not let the MSB admission layer
    # erase an explicit limitation/open-problem signal before the causal-source
    # role audit can bind it back to the SH object and chain fragments.
    record_keys = {
        str(record.get("paper_id") or record.get("evidence_id") or record.get("citation") or id(record))
        for record in records
        if isinstance(record, dict)
    }
    for raw_record in project.get("papergraph", []) or []:
        if not isinstance(raw_record, dict) or raw_record.get("active", True) is False:
            continue
        if not isinstance(raw_record.get("gap_signals"), list) or not raw_record.get("gap_signals"):
            continue
        record_key = str(
            raw_record.get("paper_id")
            or raw_record.get("evidence_id")
            or raw_record.get("citation")
            or id(raw_record)
        )
        if record_key in record_keys:
            continue
        record_keys.add(record_key)
        records.append(raw_record)
    for record in records:
        signals = record.get("gap_signals", [])
        if not isinstance(signals, list):
            continue
        citation = str(record.get("citation") or record.get("title") or "")
        method = normalize_label(record.get("method", ""))
        scenario = normalize_label(record.get("scenario", ""))
        alignment_assessment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        branch = normalized_subhypothesis_id(
            record.get("retrieval_branch")
            or record.get("sub_hypothesis_id")
            or alignment_assessment.get("sub_hypothesis_id")
        )
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            text = str(signal.get("text", "")).strip()
            if not text:
                continue
            signal_type = str(signal.get("signal_type") or "gap_signal")
            gap_type = "problem" if signal_type in {"open_problem", "challenge", "missing_evidence"} else "improvement"
            refs = unique_preserve_order([str(signal.get("supporting_reference") or ""), citation])
            source_location = signal.get("source_location") if isinstance(signal.get("source_location"), dict) else {}
            context_binding = bind_gap_predicate_context(
                project, record, branch, text, source_location,
            )
            source_unit = dict(context_binding.get("gap_predicate_source_unit") or {})
            epistemic = explicit_gap_predicate_assessment(text)
            gap = make_gap(
                gap_type="direct_gap_signal" if epistemic.get("passes") else gap_type,
                description=(
                    f"PDF/full-text {signal_type.replace('_', ' ')} signal"
                    f"{f' for {method} in {scenario}' if method and scenario and not is_unknown_value(method) and not is_unknown_value(scenario) else ''}: {text}"
                ),
                supporting_references=refs,
                suggested_research_path=research_path_for_gap_signal(signal_type, method, scenario),
                value_argument=(
                    "This gap is grounded in an explicit limitations/future-work/open-problem statement extracted from the source text, "
                    "so it provides strong handoff material for TanXi prioritization."
                ),
            )
            assessed = assess_gap_dict(project, gap)
            assessed["gap_signal"] = {
                "signal_type": signal_type,
                "text": text,
                "supporting_reference": str(signal.get("supporting_reference") or citation),
                "confidence": signal.get("confidence"),
                "evidence_type": signal.get("evidence_type"),
                "paper_id": source_unit.get("paper_id"),
                "source_location": source_location,
                "source_unit_id": source_unit.get("source_unit_id"),
                "excerpt_hash": source_unit.get("excerpt_hash"),
                "source_field": source_unit.get("source_field"),
                "section": source_unit.get("section"),
                "sentence_start": source_unit.get("sentence_start"),
                "sentence_end": source_unit.get("sentence_end"),
                "source_text_status": context_binding.get("status"),
                "gap_predicate_fragment_ref": context_binding.get("gap_predicate_fragment_ref"),
                "object_context_fragment_refs": list(context_binding.get("object_context_fragment_refs") or []),
                "causal_role_fragment_refs": list(context_binding.get("causal_role_fragment_refs") or []),
            }
            assessed["source_evidence_units"] = [source_unit]
            assessed["gap_predicate_fragment_ref"] = context_binding.get("gap_predicate_fragment_ref")
            assessed["object_context_fragment_refs"] = list(context_binding.get("object_context_fragment_refs") or [])
            assessed["causal_role_fragment_refs"] = list(context_binding.get("causal_role_fragment_refs") or [])
            assessed["contextual_source_evidence_units"] = list(
                context_binding.get("contextual_source_evidence_units") or []
            )
            assessed["source_text_status"] = context_binding.get("status")
            assessed["source_context_binding"] = context_binding
            assessed["sub_hypothesis_id"] = branch
            assessed["source_candidate_provenance"] = {
                "paper_id": str(source_unit.get("paper_id") or ""),
                "source_unit_id": str(source_unit.get("source_unit_id") or ""),
                "source_location": dict(source_unit.get("source_location") or {}),
                "excerpt_hash": str(source_unit.get("excerpt_hash") or ""),
                "sub_hypothesis_id": branch,
            }
            assessed["source_text_handoffs"] = build_source_text_handoffs(
                project,
                assessed,
                source_units=[source_unit],
                source_origin="gap_signal",
                gap_signal=assessed["gap_signal"],
            )
            assessed["evidence_lineage"] = compact_source_text_handoff_lineage(
                assessed["source_text_handoffs"]
            )
            assessed["gap_epistemic_audit"] = epistemic
            assessed["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL if epistemic.get("passes") else SECONDARY_RESEARCH_OPPORTUNITY_POOL
            # The assessment consumes source units and the explicit predicate,
            # so it must run after those fields have been attached.
            assessed = assess_gap_dict(project, assessed)
            assessed["source_text_handoffs"] = normalize_source_text_handoffs(
                assessed.get("source_text_handoffs")
            )
            assessed["evidence_lineage"] = compact_source_text_handoff_lineage(
                assessed["source_text_handoffs"]
            )
            gaps.append(assessed)
            if len(gaps) >= limit:
                return gaps
    return gaps

def detect_mechanism_issue_gaps(project: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_label, normalize_space, unique_preserve_order
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import normalize_label, normalize_space, unique_preserve_order
    gaps: list[dict[str, Any]] = []
    records, _ = admitted_method_scenario_benchmark_records(
        project_records_for_mapping(project),
        allow_noncore_context=True,
    )
    for record in records:
        if len(gaps) >= limit:
            break
        citation = record_reference(record)
        method = normalize_label(record.get("method", ""))
        scenario = normalize_label(record.get("scenario", ""))
        benchmark = normalize_label(record.get("benchmark", ""))
        alignment_assessment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        branch = normalized_subhypothesis_id(
            record.get("retrieval_branch")
            or record.get("sub_hypothesis_id")
            or alignment_assessment.get("sub_hypothesis_id")
        )
        text = normalize_space(
            " ".join(
                str(record.get(key, ""))
                for key in ("limitation", "conclusion", "abstract", "full_text_excerpt", "contribution")
                if record.get(key)
            )
        )
        candidate_signals = list(record.get("gap_signals", []) if isinstance(record.get("gap_signals"), list) else [])
        candidate_signals.extend(extract_mechanism_issue_signals(text, citation=citation))
        for signal in normalize_gap_signals(candidate_signals, citation=citation, limit=8):
            if len(gaps) >= limit:
                break
            signal_text = str(signal.get("text") or "")
            issue_axis = mechanism_issue_axis(signal_text)
            epistemic = explicit_gap_predicate_assessment(signal_text)
            if not issue_axis or not epistemic.get("passes"):
                continue
            source_location = signal.get("source_location") if isinstance(signal.get("source_location"), dict) else {}
            context_binding = bind_gap_predicate_context(
                project, record, branch, signal_text, source_location,
            )
            source_unit = dict(context_binding.get("gap_predicate_source_unit") or {})
            gap = make_gap(
                gap_type="mechanism_problem",
                description=mechanism_gap_description(issue_axis, signal_text, method, scenario, benchmark),
                supporting_references=unique_preserve_order([str(signal.get("supporting_reference") or ""), citation]),
                suggested_research_path=mechanism_gap_research_path(issue_axis, method, scenario, benchmark),
                value_argument=(
                    "This gap is grounded in a source-level mechanism/limitation/challenge statement, "
                    "so it should outrank bare method-scenario matrix holes."
                ),
            )
            assessed = assess_gap_dict(project, gap)
            assessed["mechanism_issue_signal"] = {
                "axis": issue_axis,
                "source_text": signal_text,
                "signal_type": signal.get("signal_type"),
                "confidence": signal.get("confidence"),
                "gap_predicate": epistemic,
                "paper_id": source_unit.get("paper_id"),
                "source_location": source_location,
                "source_unit_id": source_unit.get("source_unit_id"),
                "excerpt_hash": source_unit.get("excerpt_hash"),
                "source_field": source_unit.get("source_field"),
                "section": source_unit.get("section"),
                "sentence_start": source_unit.get("sentence_start"),
                "sentence_end": source_unit.get("sentence_end"),
                "source_text_status": context_binding.get("status"),
                "gap_predicate_fragment_ref": context_binding.get("gap_predicate_fragment_ref"),
                "object_context_fragment_refs": list(context_binding.get("object_context_fragment_refs") or []),
                "causal_role_fragment_refs": list(context_binding.get("causal_role_fragment_refs") or []),
            }
            assessed["source_evidence_units"] = [source_unit]
            assessed["gap_predicate_fragment_ref"] = context_binding.get("gap_predicate_fragment_ref")
            assessed["object_context_fragment_refs"] = list(context_binding.get("object_context_fragment_refs") or [])
            assessed["causal_role_fragment_refs"] = list(context_binding.get("causal_role_fragment_refs") or [])
            assessed["contextual_source_evidence_units"] = list(
                context_binding.get("contextual_source_evidence_units") or []
            )
            assessed["source_text_status"] = context_binding.get("status")
            assessed["source_context_binding"] = context_binding
            assessed["sub_hypothesis_id"] = branch
            assessed["source_candidate_provenance"] = {
                "paper_id": str(source_unit.get("paper_id") or ""),
                "source_unit_id": str(source_unit.get("source_unit_id") or ""),
                "source_location": dict(source_unit.get("source_location") or {}),
                "excerpt_hash": str(source_unit.get("excerpt_hash") or ""),
                "sub_hypothesis_id": branch,
            }
            assessed["source_text_handoffs"] = build_source_text_handoffs(
                project,
                assessed,
                source_units=[source_unit],
                source_origin="mechanism_issue_signal",
                gap_signal=assessed["mechanism_issue_signal"],
            )
            assessed["evidence_lineage"] = compact_source_text_handoff_lineage(
                assessed["source_text_handoffs"]
            )
            assessed["gap_epistemic_audit"] = epistemic
            assessed["gap_candidate_pool"] = COMPOSITE_GAP_AUDIT_POOL
            # Avoid the transient no-predicate score produced before the
            # paper-qualified mechanism issue was attached.
            assessed = assess_gap_dict(project, assessed)
            assessed["source_text_handoffs"] = normalize_source_text_handoffs(
                assessed.get("source_text_handoffs")
            )
            assessed["evidence_lineage"] = compact_source_text_handoff_lineage(
                assessed["source_text_handoffs"]
            )
            gaps.append(assessed)
    return dedupe_knowledge_gaps(gaps)[:limit]

def extract_mechanism_issue_signals(text: str, *, citation: str = "", limit: int = 12) -> list[dict[str, Any]]:
    try:
        from ._utils import new_id, split_sentences, trim_text
    except ImportError:
        from _utils import new_id, split_sentences, trim_text
    signals: list[dict[str, Any]] = []
    for sentence in split_sentences(text):
        axis = mechanism_issue_axis(sentence)
        epistemic = explicit_gap_predicate_assessment(sentence)
        if not axis or not epistemic.get("passes"):
            continue
        if len(sentence.split()) < 6:
            continue
        signals.append(
            {
                "signal_id": new_id("sig"),
                "signal_type": "mechanism_issue",
                "issue_axis": axis,
                "text": trim_text(sentence, 420),
                "evidence_type": "mechanism_problem_statement",
                "supporting_reference": citation,
                "confidence": mechanism_issue_confidence(axis, sentence),
                "gap_predicate": epistemic,
            }
        )
    signals.sort(key=lambda item: (-float(item.get("confidence", 0.0)), item.get("issue_axis", ""), item.get("text", "")))
    return signals[:limit]

def mechanism_issue_axis(text: str) -> str:
    lowered = text.lower()
    axis_rules = [
        ("adverse_effect_or_safety", ("toxicity", "toxic", "safety", "adverse", "side effect", "risk", "hazard", "failure mode")),
        ("heterogeneity_or_subgroup", ("heterogeneity", "heterogeneous", "subgroup", "escape", "variation", "variability", "stratification", "combination", "combinatorial")),
        ("persistence_or_context_stress", ("persistence", "fatigue", "exhaustion", "stress", "environment", "microenvironment", "context", "adaptation", "infiltration")),
        ("interface_or_boundary_degradation", ("interface", "interfacial", "boundary", "surface", "degradation", "side reaction", "leakage", "drift", "decay", "aging")),
        ("operating_regime_stability", ("voltage", "temperature", "pressure", "frequency", "load", "scale", "resolution", "stability", "cycling", "retention", "capacity fading")),
        ("mechanism_uncertainty", ("mechanism", "remain unclear", "remains unclear", "unclear", "not understood", "unknown", "debate")),
        ("data_measurement_gap", ("lack of", "limited data", "insufficient", "scarce", "underexplored", "not measured", "no dataset")),
        ("generalization_robustness", ("generalization", "robustness", "failure mode", "distribution shift", "scale", "scalable", "reproducibility")),
    ]
    for axis, terms in axis_rules:
        if any(term in lowered for term in terms):
            return axis
    return ""

def mechanism_issue_confidence(axis: str, sentence: str) -> float:
    confidence = 0.78
    lowered = sentence.lower()
    if any(term in lowered for term in ("remain unclear", "remains unclear", "challenge", "limitation", "failure", "degradation", "adverse", "risk")):
        confidence += 0.08
    if axis in {"adverse_effect_or_safety", "interface_or_boundary_degradation", "operating_regime_stability"}:
        confidence += 0.04
    if any(term in lowered for term in ("may", "could", "might")):
        confidence -= 0.04
    return round(max(0.1, min(0.98, confidence)), 3)

def mechanism_gap_description(axis: str, signal_text: str, method: str, scenario: str, benchmark: str) -> str:
    try:
        from ._utils import is_unknown_value, trim_text
    except ImportError:
        from _utils import is_unknown_value, trim_text
    context = []
    if method and not is_unknown_value(method):
        context.append(f"method={method}")
    if scenario and not is_unknown_value(scenario):
        context.append(f"scenario={scenario}")
    if benchmark and not is_unknown_value(benchmark):
        context.append(f"benchmark={benchmark}")
    prefix = f"Source-grounded mechanism gap ({axis.replace('_', ' ')})"
    if context:
        prefix += f" for {', '.join(context)}"
    return f"{prefix}: {trim_text(signal_text, 360)}"

def mechanism_gap_research_path(axis: str, method: str, scenario: str, benchmark: str) -> str:
    if axis == "adverse_effect_or_safety":
        return "Map intended effects against adverse effects across relevant contexts, then test whether the proposed intervention improves benefit-risk without hiding failure modes."
    if axis == "heterogeneity_or_subgroup":
        return "Quantify heterogeneity, identify subgroup-specific failure modes, and test single versus combined strategies under explicit stratified benchmarks."
    if axis == "persistence_or_context_stress":
        return "Measure persistence under contextual stress and compare against interventions that change the suspected stress pathway."
    if axis == "interface_or_boundary_degradation":
        return "Isolate boundary or interface degradation pathways with matched diagnostics and test protective modifications under accelerated stress."
    if axis == "operating_regime_stability":
        return "Run operating-regime stress tests with mechanism-specific readouts to separate headline performance from mechanism fidelity."
    if axis == "mechanism_uncertainty":
        return "Convert the unclear mechanism into competing causal explanations and design an experiment or simulation that distinguishes them."
    if axis == "data_measurement_gap":
        return "Collect or retrieve the missing measurement layer, then evaluate whether the original claim survives the added data modality."
    return "Define the failure mode, perturb the suspected mechanism, and test whether the benchmark changes in the predicted direction."

def research_path_for_gap_signal(signal_type: str, method: str, scenario: str) -> str:
    try:
        from ._utils import is_unknown_value
    except ImportError:
        from _utils import is_unknown_value
    target = f" for {method} in {scenario}" if method and scenario and not is_unknown_value(method) and not is_unknown_value(scenario) else ""
    if signal_type == "future_work":
        return f"Translate the source's future-work statement into a falsifiable hypothesis{target}, then define baseline comparisons and success criteria."
    if signal_type == "limitation":
        return f"Design an ablation or stress-test study that directly attacks the documented limitation{target}."
    if signal_type == "open_problem":
        return f"Decompose the open problem into mechanism, data, and benchmark subquestions{target}, then test the most tractable subquestion first."
    if signal_type == "challenge":
        return f"Identify the technical bottleneck behind the challenge{target}, then evaluate candidate methods against a failure-mode benchmark."
    return f"Run a targeted evidence expansion and validation study{target}."

def detect_problem_gaps(project: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import trim_text
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import trim_text
    problem_terms = ("open problem", "challenge", "unsolved", "remain unclear", "bottleneck", "failure", "degradation", "instability")
    gaps: list[dict[str, Any]] = []
    for record in project_records_for_mapping(project):
        text = " ".join(str(record.get(key, "")) for key in ("abstract", "conclusion", "limitation", "contribution"))
        if not any(term in text.lower() for term in problem_terms):
            continue
        citation = str(record.get("citation") or record.get("title") or "")
        gap = make_gap(
            gap_type="problem",
            description=f"Source literature indicates a recognized unresolved problem: {trim_text(text, 260)}",
            supporting_references=[citation],
            suggested_research_path="Translate the unresolved problem into a falsifiable hypothesis with acceptance criteria and failure diagnostics.",
            value_argument="Problem gaps are grounded in explicit source statements about unresolved mechanisms or practical bottlenecks.",
        )
        gaps.append(assess_gap_dict(project, gap))
        if len(gaps) >= limit:
            break
    return gaps

def local_idea_overlap(project: dict[str, Any], idea: str) -> list[dict[str, Any]]:
    try:
        from ._literature_search import query_terms
        from ._pipeline import project_records_for_mapping
    except ImportError:
        from _literature_search import query_terms
        from _pipeline import project_records_for_mapping
    terms = set(query_terms(idea))
    if not terms:
        return []
    matches: list[dict[str, Any]] = []
    for record in project_records_for_mapping(project):
        text = " ".join(str(record.get(key, "")) for key in ("title", "abstract", "contribution", "limitation", "method", "scenario", "benchmark"))
        record_terms = set(query_terms(text))
        if not record_terms:
            continue
        overlap = len(terms & record_terms) / max(1, len(terms))
        if overlap <= 0:
            continue
        matches.append(
            {
                "overlap_score": round(overlap, 4),
                "matched_terms": sorted(terms & record_terms)[:12],
                "title": record.get("title", ""),
                "citation": record.get("citation", ""),
                "venue": record.get("venue", ""),
            }
        )
    matches.sort(key=lambda item: (-float(item["overlap_score"]), item.get("title", "")))
    return matches

def literature_coverage_factor(project: dict[str, Any], description: str) -> float:
    try:
        from ._literature_search import query_terms
        from ._pipeline import project_records_for_mapping
        from ._utils import record_context_text
    except ImportError:
        from _literature_search import query_terms
        from _pipeline import project_records_for_mapping
        from _utils import record_context_text
    terms = set(query_terms(description))
    if not terms:
        return 0.0
    records = project_records_for_mapping(project)
    if not records:
        return 0.0
    covered_terms: set[str] = set()
    matching_records = 0
    for record in records:
        record_terms = set(query_terms(record_context_text(record)))
        overlap = terms & record_terms
        if overlap:
            matching_records += 1
            covered_terms.update(overlap)
    term_coverage = len(covered_terms) / max(1, len(terms))
    record_coverage = min(1.0, matching_records / max(3, len(records)))
    return round(0.7 * term_coverage + 0.3 * record_coverage, 4)

def summarize_uniqueness_live_search(result: dict[str, Any]) -> dict[str, Any]:
    if not result:
        return {"used": False}
    return {
        "used": True,
        "status": result.get("status", "ok") if "status" in result else "ok",
        "search_id": result.get("search_id"),
        "total_results": result.get("total_results", 0),
        "top_titles": [item.get("title") for item in result.get("results", [])[:5] if isinstance(item, dict)],
    }

def zhizhi_standard_output(
    thought: str,
    action: dict[str, Any],
    knowledge_map: dict[str, Any],
    gaps: list[dict[str, Any]],
    observations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "thought": thought,
        "action": action,
        "observation": observations or [],
        "knowledge_map_summary": {
            "main_methods": knowledge_map.get("main_methods", []),
            "method_scenario_coverage": knowledge_map.get("method_scenario_coverage", {}),
            "method_scenario_benchmark_triples": knowledge_map.get("method_scenario_benchmark_triples", [])[:20],
            "claim_type_counts": knowledge_map.get("claim_type_counts", {}),
        },
        "knowledge_gaps": [
            {
                "gap_id": gap.get("gap_id"),
                "gap_type": gap.get("gap_type"),
                "description": gap.get("description"),
                "supporting_references": gap.get("supporting_references", []),
                "novelty_score": gap.get("novelty_score"),
                "application_value": gap.get("application_value"),
                "feasibility": gap.get("feasibility"),
                "suggested_research_path": gap.get("suggested_research_path"),
                "value_argument": gap.get("value_argument", ""),
                "overlap_risk": gap.get("overlap_risk", ""),
                "requires_human_review": gap.get("requires_human_review", False),
            }
            for gap in gaps
        ],
        "self_reflection": {
            "top_venue_coverage_checked": True,
            "pseudo_gap_risk_checked": True,
            "method_categories_require_literature_support": True,
            "unsupported_claims_marked_for_review": True,
        },
    }

def knowledge_map_unknown_summary(knowledge_map: dict[str, Any]) -> dict[str, int]:
    triples = knowledge_map.get("method_scenario_benchmark_triples", [])
    unknown_triples = 0
    for triple in triples:
        if not isinstance(triple, dict):
            continue
        values = [str(triple.get(key, "")).lower() for key in ("method", "scenario", "benchmark")]
        if any(value.startswith("unknown") or value.startswith("unspecified") for value in values):
            unknown_triples += 1
    return {"total_triples": len(triples), "unknown_triples": unknown_triples}

def extract_gap_signals_from_text(
    text: str,
    *,
    citation: str = "",
    limit: int = 12,
    evidence_spans: list[dict[str, Any]] | None = None,
    source_url: str = "",
    paper_id: str = "",
    sub_hypothesis_id: str = "",
) -> list[dict[str, Any]]:
    try:
        from ._utils import new_id, normalize_space, split_sentences, trim_text
    except ImportError:
        from _utils import new_id, normalize_space, split_sentences, trim_text
    clean = normalize_space(text)
    if not clean:
        return []
    focused = extract_gap_relevant_sections(clean)
    candidate_text = "\n".join(focused) if focused else clean
    signals: list[dict[str, Any]] = []
    for sentence in split_sentences(candidate_text):
        signal_type = classify_gap_signal(sentence)
        if not signal_type:
            continue
        rendered = trim_text(sentence, 360)
        if len(rendered) < 25:
            continue
        source_location = gap_signal_location(rendered, evidence_spans, source_url)
        excerpt_hash = sha256(rendered.encode("utf-8")).hexdigest()
        source_field = str(
            source_location.get("source_field")
            or source_location.get("section")
            or "unresolved"
        )
        locator = re.sub(r"[^A-Za-z0-9_.:-]+", "_", source_field).strip("_") or "unresolved"
        signals.append(
            {
                "signal_id": new_id("sig"),
                "signal_type": signal_type,
                "text": rendered,
                "evidence_type": "author_opinion" if signal_type in {"future_work", "limitation"} else "problem_statement",
                "supporting_reference": citation,
                "confidence": gap_signal_confidence(signal_type, sentence),
                "source_location": source_location,
                "paper_id": str(paper_id or ""),
                "source_unit_id": (
                    f"{paper_id}:{locator}:gap_signal:{excerpt_hash[:16]}"
                    if paper_id else ""
                ),
                "excerpt_hash": excerpt_hash,
                "source_field": source_field,
                "sub_hypothesis_id": str(sub_hypothesis_id or ""),
            }
        )
    signals.sort(key=lambda item: (-float(item["confidence"]), item["signal_type"], item["text"]))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        key = gap_signature(str(signal.get("text", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
        if len(deduped) >= limit:
            break
    return deduped

def extract_gap_relevant_sections(text: str) -> list[str]:
    try:
        from ._utils import extract_section, trim_text, unique_preserve_order
    except ImportError:
        from _utils import extract_section, trim_text, unique_preserve_order
    sections: list[str] = []
    headings = [
        "limitations",
        "limitation",
        "future work",
        "future directions",
        "outlook",
        "discussion",
        "conclusion",
        "conclusions",
        "remaining challenges",
        "open problems",
        "perspectives",
    ]
    for heading in headings:
        section = extract_section(text, [heading])
        if section:
            sections.append(section)
    section_matches = re.finditer(
        r"\[SECTION:\s*(?P<heading>[^|\]]+?)(?:\s*\|\s*pages?[^\]]*)?\]\s*(?P<body>.*?)(?=\n\s*\[SECTION:|\n\s*\[(?:KEYWORD|TABLES|FIGURE)|\Z)",
        str(text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in section_matches:
        heading = str(match.group("heading") or "").lower()
        if any(term in heading for term in headings):
            sections.append(str(match.group("body") or ""))
    return unique_preserve_order([trim_text(section, 3000) for section in sections if section])

def classify_gap_signal(sentence: str) -> str:
    lowered = sentence.lower()
    if any(term in lowered for term in ("future work", "future research", "future direction", "should investigate", "warrants further", "\u672a\u6765\u7814\u7a76", "\u6709\u5f85\u8fdb\u4e00\u6b65")):
        return "future_work"
    if any(term in lowered for term in ("limitation", "limited by", "we did not", "does not address", "cannot", "unable to", "\u5c40\u9650\u6027", "\u53d7\u9650\u4e8e", "\u65e0\u6cd5")):
        return "limitation"
    if any(term in lowered for term in ("remain unclear", "remains unclear", "unknown", "open problem", "unresolved", "not well understood", "\u5c1a\u4e0d\u6e05\u695a", "\u672a\u89e3\u51b3", "\u4e0d\u660e\u786e")):
        return "open_problem"
    if any(term in lowered for term in ("challenge", "bottleneck", "barrier", "difficult", "failure mode", "degradation")):
        return "challenge"
    if any(term in lowered for term in ("needs", "requires", "lack of", "scarce", "insufficient", "underexplored")):
        return "missing_evidence"
    if mechanism_issue_axis(sentence) and explicit_gap_predicate_assessment(sentence).get("passes"):
        return "mechanism_issue"
    return ""


def gap_signal_location(
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

def gap_signal_confidence(signal_type: str, sentence: str) -> float:
    base = {
        "future_work": 0.78,
        "limitation": 0.82,
        "open_problem": 0.88,
        "challenge": 0.76,
        "missing_evidence": 0.72,
        "mechanism_issue": 0.84,
    }.get(signal_type, 0.6)
    lowered = sentence.lower()
    if any(term in lowered for term in ("we", "our", "this study", "the present study")):
        base += 0.05
    if any(term in lowered for term in ("may", "could", "might")):
        base -= 0.05
    return round(max(0.1, min(0.98, base)), 3)

def normalize_gap_signals(
    signals: list[dict[str, Any]],
    *,
    citation: str = "",
    limit: int = 16,
    paper_id: str = "",
    sub_hypothesis_id: str = "",
) -> list[dict[str, Any]]:
    try:
        from ._utils import new_id, trim_text
    except ImportError:
        from _utils import new_id, trim_text
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        text = trim_text(str(signal.get("text", "")), 360)
        if not text:
            continue
        key = gap_signature(text)
        if key in seen:
            continue
        seen.add(key)
        signal_type = str(signal.get("signal_type") or classify_gap_signal(text) or "gap_signal")
        item = {
            "signal_id": str(signal.get("signal_id") or new_id("sig")),
            "signal_type": signal_type,
            "text": text,
            "evidence_type": str(signal.get("evidence_type") or ("author_opinion" if signal_type in {"future_work", "limitation"} else "problem_statement")),
            "supporting_reference": str(signal.get("supporting_reference") or citation),
            "confidence": float(signal.get("confidence") or gap_signal_confidence(signal_type, text)),
        }
        source_location = (
            dict(signal["source_location"])
            if isinstance(signal.get("source_location"), dict)
            else {"status": "UNRESOLVED_SOURCE_LOCATION"}
        )
        item["source_location"] = source_location
        resolved_paper_id = str(signal.get("paper_id") or paper_id or "")
        excerpt_hash = str(signal.get("excerpt_hash") or sha256(text.encode("utf-8")).hexdigest())
        source_field = str(
            signal.get("source_field")
            or source_location.get("source_field")
            or source_location.get("section")
            or "unresolved"
        )
        locator = re.sub(r"[^A-Za-z0-9_.:-]+", "_", source_field).strip("_") or "unresolved"
        item.update({
            "paper_id": resolved_paper_id,
            "source_unit_id": str(
                signal.get("source_unit_id")
                or (
                    f"{resolved_paper_id}:{locator}:gap_signal:{excerpt_hash[:16]}"
                    if resolved_paper_id else ""
                )
            ),
            "excerpt_hash": excerpt_hash,
            "source_field": source_field,
            "sub_hypothesis_id": str(signal.get("sub_hypothesis_id") or sub_hypothesis_id or ""),
        })
        for key in ("sentence_start", "sentence_end"):
            if signal.get(key) not in (None, ""):
                item[key] = signal.get(key)
        if isinstance(signal.get("gap_predicate"), dict):
            item["gap_predicate"] = dict(signal["gap_predicate"])
        normalized.append(item)
        if len(normalized) >= limit:
            break
    normalized.sort(key=lambda item: (-float(item["confidence"]), item["signal_type"], item["text"]))
    return normalized


# ---------------------------------------------------------------------------
# TABI: Toulmin-Abductive Bucketed Inference
# ---------------------------------------------------------------------------

def extract_evidence_pairs_from_records(project, limit=30):
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import normalize_space, trim_text
    records = project_records_for_mapping(project)
    pairs = []
    # A contradiction pair requires a matched comparison contract and
    # opposite claims.  Merely wording two conclusions differently is not a
    # contradiction.
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            relation = contradiction_relation(left, right)
            if not relation.get("contradiction"):
                continue
            left_claim = str(relation.get("left_claim") or "")
            right_claim = str(relation.get("right_claim") or "")
            pairs.append({
                "pair_type": "contradiction",
                "sub_hypothesis_id": str(relation.get("sub_hypothesis_id") or ""),
                "grounds_a": {
                    "text": trim_text(left_claim, 300),
                    "reference": record_reference(left),
                    "paper_id": str(left.get("paper_id") or ""),
                    "source_evidence": bind_record_source_unit(left, left_claim, {}),
                },
                "grounds_b": {
                    "text": trim_text(right_claim, 300),
                    "reference": record_reference(right),
                    "paper_id": str(right.get("paper_id") or ""),
                    "source_evidence": bind_record_source_unit(right, right_claim, {}),
                },
                "shared_context": str(relation.get("shared_context") or ""),
                "comparability_contract": relation.get("comparability_contract"),
            })

    # Causal composition is identity based: the first chain's normalized
    # outcome must be the second chain's normalized trigger.  Shared words do
    # not establish a causal junction.
    chain_claims: list[dict[str, Any]] = []
    for record in records:
        for chain in record.get("causal_chains", []) if isinstance(record.get("causal_chains"), list) else []:
            if not isinstance(chain, dict):
                continue
            trigger = str(chain.get("trigger") or "").strip()
            outcome = str(chain.get("outcome") or "").strip()
            if not trigger or not outcome:
                continue
            evidence_text = str(chain.get("outcome_evidence") or chain.get("trigger_evidence") or f"{trigger} -> {outcome}")
            context = causal_context_from_record(record)
            chain_context = chain.get("context") if isinstance(chain.get("context"), dict) else {}
            context.update({str(key): str(value) for key, value in chain_context.items() if str(value).strip()})
            chain_claims.append({
                "trigger": trigger,
                "outcome": outcome,
                "trigger_key": canonical_causal_node_key(trigger),
                "outcome_key": canonical_causal_node_key(outcome),
                "mediator_keys": [
                    canonical_causal_node_key(
                        str(step.get("claim") or step.get("text") or "") if isinstance(step, dict) else str(step)
                    )
                    for step in (chain.get("steps") or [])
                    if isinstance(step, dict)
                    if str(step.get("claim") or step.get("text") or "").strip()
                ],
                "text": trim_text(evidence_text, 300),
                "reference": record_reference(record),
                "paper_id": str(record.get("paper_id") or ""),
                "sub_hypothesis_id": str(record.get("retrieval_branch") or chain.get("sub_hypothesis_id") or ""),
                "context": context,
                "source_evidence": bind_record_source_unit(
                    record,
                    evidence_text,
                    chain.get("outcome_location") if isinstance(chain.get("outcome_location"), dict) else {},
                ),
            })
    for first in chain_claims:
        for second in chain_claims:
            if first is second or first["paper_id"] == second["paper_id"]:
                continue
            second_input_or_mediators = {second["trigger_key"], *second.get("mediator_keys", [])} - {""}
            if not first["outcome_key"] or first["outcome_key"] not in second_input_or_mediators:
                continue
            context_match = causal_edge_context_compatibility(first, second)
            if not context_match.get("compatible"):
                continue
            pairs.append({
                "pair_type": "causal_chain_gap",
                "sub_hypothesis_id": str(first.get("sub_hypothesis_id") or ""),
                "grounds_a": {
                    "text": first["text"], "reference": first["reference"],
                    "paper_id": first["paper_id"], "source_evidence": first["source_evidence"],
                },
                "grounds_b": {
                    "text": second["text"], "reference": second["reference"],
                    "paper_id": second["paper_id"], "source_evidence": second["source_evidence"],
                },
                "shared_context": f"normalized_causal_identity={first['outcome_key']}",
                "context_compatibility": context_match,
            })
    condition_markers = [
        ("under", "condition"), ("at", "level"), ("in", "environment"),
        ("for", "case"), ("when", "scenario"), ("within", "range"),
        ("above", "threshold"), ("below", "threshold"),
    ]
    for rec in records:
        lim = normalize_space(str(rec.get("limitation") or ""))
        if not lim or len(lim) < 20:
            continue
        for marker, kind in condition_markers:
            if f" {marker} " in lim.lower():
                pairs.append({
                    "pair_type": "extrapolation_limit",
                    "grounds_a": {
                        "text": trim_text(lim, 300),
                        "reference": record_reference(rec),
                        "scenario": str(rec.get("scenario", "")),
                        "paper_id": str(rec.get("paper_id") or ""),
                        "source_evidence": bind_record_source_unit(rec, lim, {}),
                    },
                    "grounds_b": {
                        "text": f"Validity claimed {marker} specific {kind}; generalization to other {kind}s is unverified",
                        "reference": record_reference(rec),
                        "scenario": str(rec.get("scenario", "")),
                        "paper_id": str(rec.get("paper_id") or ""),
                        "source_evidence": bind_record_source_unit(rec, lim, {}),
                    },
                    "shared_context": f"extrapolation from {kind} '{marker}'",
                })
                break
    return pairs[:limit]


def tabi_mechanism_assessment(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Audit whether a TABI gap contains an actual theory/evidence tension.

    The function never invents a quantitative prediction.  It reports a
    substantive TABI result only when the local evidence includes both a
    theory/model claim and an empirical/observational claim; otherwise it
    records exactly which evidence class must be retrieved next.
    """
    try:
        from ._utils import trim_text, unique_preserve_order
    except ImportError:
        from _utils import trim_text, unique_preserve_order
    refs = {str(ref) for ref in gap.get("supporting_references", []) if str(ref)}
    records = mechanism_core_records(project)
    selected = [
        record for record in records
        if not refs or str(record.get("citation") or record.get("title") or "") in refs
    ]
    if not selected:
        selected = records[:8]
    theory_markers = ("theory", "theoretical", "model", "simulation", "computed", "calculated", "predicted")
    empirical_markers = ("experiment", "experimental", "measured", "observed", "operando", "in situ", "characterized", "data")
    theory, empirical, mechanisms = [], [], []
    for record in selected:
        text = " ".join(str(record.get(field) or "") for field in ("abstract", "contribution", "conclusion", "limitation"))
        lowered = text.lower()
        citation = str(record.get("citation") or record.get("title") or "")
        excerpt = trim_text(text, 300)
        if any(marker in lowered for marker in theory_markers):
            theory.append({"citation": citation, "excerpt": excerpt})
        if any(marker in lowered for marker in empirical_markers):
            empirical.append({"citation": citation, "excerpt": excerpt})
        mechanism = str(record.get("method") or record.get("scenario") or "").strip()
        if mechanism:
            mechanisms.append(mechanism)
    composite_contract = gap.get("composite_evidence_contract") if isinstance(gap.get("composite_evidence_contract"), dict) else {}
    explicit_tension = bool(composite_contract.get("status") == "PASSED")
    evidence_gap: list[str] = []
    if not theory:
        evidence_gap.append("No theory/model source is linked to this gap.")
    if not empirical:
        evidence_gap.append("No empirical/observational source is linked to this gap.")
    if not explicit_tension:
        evidence_gap.append("The source pair does not yet establish a theory--observation contradiction.")
    substantive = bool(explicit_tension)
    score = min(10, (4 if theory else 0) + (4 if empirical else 0) + (2 if explicit_tension else 0))
    variable = _first_tabi_variable(gap)
    return {
        "theory_consistency": {
            "status": "tension_detected" if substantive else "insufficient_comparison",
            "theory_evidence": theory[:2],
            "empirical_evidence": empirical[:2],
        },
        "counterfactual": {
            "status": "testable" if variable else "needs_variable",
            "condition": f"Hold confounders fixed and vary {variable}." if variable else "Extract a controllable variable from the linked studies.",
        },
        "mechanism_competition": {
            "candidates": unique_preserve_order(mechanisms)[:3],
            "status": "compare_candidates" if len(set(mechanisms)) >= 2 else "needs_competing_mechanism_evidence",
        },
        "evidence_gap": evidence_gap,
        "testable_prediction": (
            f"A parameter-matched intervention on {variable} should discriminate the competing explanations before endpoint performance changes."
            if variable else "No quantitative prediction is asserted until a controllable variable and matched evidence are retrieved."
        ),
        "contradiction_score": score,
        "substantive": substantive,
        "composite_evidence_contract_status": str(composite_contract.get("status") or "NOT_PASSED"),
        "required_directed_retrieval": [
            "theory or simulation prediction", "matched experimental or observational measurement"
        ] if not substantive else [],
    }


def _first_tabi_variable(gap: dict[str, Any]) -> str:
    ingredients = gap.get("hypothesis_ingredients") if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    for field in ("numerical_bounds", "operating_conditions", "measurable_metrics"):
        values = ingredients.get(field)
        if isinstance(values, list) and values and str(values[0]).strip():
            return str(values[0]).strip()
    return ""


def build_tabi_composite_evidence_contract(pair: dict[str, Any]) -> dict[str, Any]:
    pair_type = str(pair.get("pair_type") or "")
    grounds_a = pair.get("grounds_a") if isinstance(pair.get("grounds_a"), dict) else {}
    grounds_b = pair.get("grounds_b") if isinstance(pair.get("grounds_b"), dict) else {}
    source_units = [
        dict(item)
        for item in (grounds_a.get("source_evidence"), grounds_b.get("source_evidence"))
        if isinstance(item, dict)
    ]
    if pair_type == "contradiction":
        scientific = pair.get("comparability_contract") if isinstance(pair.get("comparability_contract"), dict) else {}
        context = scientific.get("context_constraints") if isinstance(scientific.get("context_constraints"), dict) else {}
        return build_composite_evidence_contract(
            "TABI_CONTRADICTION",
            source_units,
            scientific_contract=scientific,
            required_checks={
                "same_sub_hypothesis": scientific.get("same_sub_hypothesis") is True,
                "matched_input_outcome_object": all(
                    bool(item.get("matched"))
                    for item in (scientific.get("dimensions") or {}).values()
                    if isinstance(item, dict)
                ) and len(scientific.get("dimensions") or {}) == 3,
                "matched_system_sample_or_regime": bool(context.get("matched_dimensions")),
            },
        )
    if pair_type == "causal_chain_gap":
        scientific = pair.get("context_compatibility") if isinstance(pair.get("context_compatibility"), dict) else {}
        requirements = scientific.get("requirements") if isinstance(scientific.get("requirements"), dict) else {}
        return build_composite_evidence_contract(
            "TABI_CAUSAL_COMPOSITION",
            source_units,
            scientific_contract=scientific,
            required_checks={
                "same_sub_hypothesis": requirements.get("same_sub_hypothesis") is True,
                "same_research_object": requirements.get("same_research_object") is True,
                "matched_system_sample_or_regime": requirements.get("matched_system_sample_or_regime") is True,
                "normalized_mediator_identity": "normalized_causal_identity=" in str(pair.get("shared_context") or ""),
            },
        )
    return build_composite_evidence_contract(
        "TABI_UNSUPPORTED_PAIR",
        source_units,
        scientific_contract={},
        required_checks={"supported_tabi_pair_type": False},
    )


def tabi_abductive_gap_detection(project, max_gaps=8):
    try:
        from ._utils import new_id, normalize_space, trim_text, unique_preserve_order
    except ImportError:
        from _utils import new_id, normalize_space, trim_text, unique_preserve_order
    evidence_pairs = extract_evidence_pairs_from_records(project, limit=30)
    if not evidence_pairs:
        return []
    gaps, seen_claims = [], set()
    for pair in evidence_pairs:
        pt = pair.get("pair_type", "")
        ga, gb = pair.get("grounds_a", {}), pair.get("grounds_b", {})
        sc = pair.get("shared_context", "")
        ta = normalize_space(str(ga.get("text", "")))
        tb = normalize_space(str(gb.get("text", "")))
        if not ta or not tb:
            continue
        warrant = tabi_warrant_for_pair(pt, ta, tb, sc)
        claim = tabi_abductive_claim(pt, ta, tb, warrant, sc)
        if not claim or len(claim) < 15:
            continue
        ck = gap_signature(claim)
        if ck in seen_claims:
            continue
        seen_claims.add(ck)
        bucket = tabi_bucket_confidence(pt, ta, tb, warrant)
        refs = unique_preserve_order([str(ga.get("reference", "")), str(gb.get("reference", ""))])
        composite_contract = build_tabi_composite_evidence_contract(pair)
        gap = make_gap(
            gap_type="implicit_tabi" if pt != "extrapolation_limit" else "migration",
            description=trim_text(claim, 500),
            supporting_references=[r for r in refs if r],
            suggested_research_path=tabi_research_path(pt, claim, sc),
            value_argument=f"TABI abductive inference from {pt} evidence pair.",
        )
        gap["tabi_chain"] = {
            "grounds_a": trim_text(ta, 300),
            "grounds_b": trim_text(tb, 300),
            "warrant": trim_text(warrant, 300),
            "claim": trim_text(claim, 300),
            "pair_type": pt,
            "shared_context": sc,
        }
        gap["tabi_warrant"] = trim_text(warrant, 300)
        gap["tabi_claim"] = trim_text(claim, 300)
        gap["gap_discovery_method"] = "implicit_tabi"
        gap["confidence_bucket"] = bucket
        gap["tabi_evidence_type"] = pt
        gap["sub_hypothesis_id"] = str(pair.get("sub_hypothesis_id") or "")
        gap["source_evidence_units"] = [
            dict(item)
            for item in (ga.get("source_evidence"), gb.get("source_evidence"))
            if isinstance(item, dict) and item.get("paper_id") and item.get("source_unit_id")
        ]
        gap["composite_evidence_contract"] = composite_contract
        gap["gap_candidate_pool"] = (
            COMPOSITE_GAP_AUDIT_POOL
            if composite_contract.get("status") == "PASSED"
            else SECONDARY_RESEARCH_OPPORTUNITY_POOL
        )
        gap["gap_epistemic_audit"] = {
            "passes": composite_contract.get("status") == "PASSED",
            "category": (
                "tabi_composite_contract_passed"
                if composite_contract.get("status") == "PASSED"
                else "abductive_seed_requires_composite_source_role_audit"
            ),
            "verdict": (
                "TABI_COMPOSITE_CANDIDATE"
                if composite_contract.get("status") == "PASSED"
                else "ABDUCTIVE_SECONDARY_CANDIDATE"
            ),
        }
        gap["tabi_checks"] = tabi_mechanism_assessment(project, gap)
        gap["eligible_for_hypothesis_generation"] = False
        gaps.append(gap)
        if len(gaps) >= max_gaps:
            break
    gaps.sort(key=lambda g: (0 if g.get("confidence_bucket") == "more_probable" else 1, -len(str(g.get("description", "")))))
    log_event(
        "SCIENCE",
        "tabi_raw_pattern_candidates",
        raw_patterns=len(gaps),
        pairs_evaluated=len(evidence_pairs),
        note="Pre-admission abductive patterns; not yet scientific gaps.",
    )
    return gaps


def tabi_warrant_for_pair(pt, ta, tb, sc):
    if pt == "contradiction":
        return (
            f"Two studies report conflicting findings about {sc}. "
            "When evidence contradicts, the underlying mechanism or boundary condition is likely unresolved."
        )
    if pt == "causal_chain_gap":
        return (
            f"Evidence establishes separate causal links that share intermediate terms ({sc}). "
            "If A→B and B→C are independently supported but A→C has not been directly validated, "
            "the transitive causal claim remains a knowledge gap."
        )
    if pt == "extrapolation_limit":
        return (
            f"Validity is claimed {sc}. "
            "Generalization beyond the stated condition boundary is not supported by the available evidence."
        )
    return "Evidence premises suggest an unresolved inferential gap."


def tabi_abductive_claim(pt, ta, tb, warrant, sc):
    if pt == "contradiction":
        return (
            f"The mechanism underlying the contradiction between "
            f"'{ta[:120].rstrip('.,;')}' and '{tb[:120].rstrip('.,;')}' remains unresolved. "
            f"A systematic study controlling for {sc} is needed."
        )
    if pt == "causal_chain_gap":
        return (
            f"Although individual causal links are supported "
            f"({ta[:80].rstrip('.,;')} and {tb[:80].rstrip('.,;')}), "
            "the transitive relationship has not been directly validated."
        )
    if pt == "extrapolation_limit":
        return (
            f"The evidence supports validity {ta[:100].rstrip('.,;')}, "
            "but generalization to untested conditions remains an open question."
        )
    return ""


def tabi_bucket_confidence(pt, ta, tb, warrant):
    if pt == "contradiction":
        return "more_probable"
    if pt == "causal_chain_gap":
        aw = set(re.findall(r"\w{4,}", ta.lower()))
        bw = set(re.findall(r"\w{4,}", tb.lower()))
        return "more_probable" if len(aw & bw) >= 3 else "least_probable"
    if pt == "extrapolation_limit":
        return "more_probable" if len(ta) > 40 else "least_probable"
    return "least_probable"


def tabi_research_path(pt, claim, sc):
    if pt == "contradiction":
        return "Design a controlled experiment that systematically varies the disputed parameters while holding confounders constant."
    if pt == "causal_chain_gap":
        return "Conduct an end-to-end study that directly tests the transitive causal relationship with intermediate variable monitoring."
    if pt == "extrapolation_limit":
        return "Perform a regime-shift experiment varying the boundary condition to map the validity frontier."
    return "Investigate the identified gap with targeted experiments."


# ---------------------------------------------------------------------------
# Counterfactual Gap Analysis (CG)
# ---------------------------------------------------------------------------

def counterfactual_gap_analysis(project, gaps, limit=10):
    try:
        from ._pipeline import project_records_for_mapping
    except ImportError:
        from _pipeline import project_records_for_mapping
    records = project_records_for_mapping(project)
    if not records:
        return gaps
    enriched = []
    for gap in gaps[:limit]:
        tree = build_counterfactual_tree(gap, records)
        gap["counterfactual_tree"] = tree
        gap["gap_resolution_type"] = classify_gap_counterfactual_type(tree)
        gap["leaf_conditions"] = tree.get("leaf_conditions", [])
        gap["resolution_complexity"] = tree.get("resolution_complexity", "unknown")
        enriched.append(gap)
    log_event(
        "SCIENCE", "counterfactual_gap_analysis",
        gaps_analyzed=len(enriched),
        complement=sum(1 for g in enriched if g.get("gap_resolution_type") == "complement_gap"),
        novel=sum(1 for g in enriched if g.get("gap_resolution_type") == "novel_concept_gap"),
    )
    return enriched


def build_counterfactual_tree(gap, records):
    try:
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _utils import normalize_space, trim_text
    desc = normalize_space(str(gap.get("description", "")))
    gt = str(gap.get("gap_type", ""))
    gm, gs = infer_method_scenario_from_gap(gap, records)
    related = find_related_records(gm, gs, records)
    missing = find_missing_evidence(gm, gs, records)
    branches = []
    if related:
        covered = {normalize_space(str(r.get("scenario", ""))).lower() for r in related}
        target = normalize_space(gs).lower()
        if target and target not in covered:
            branches.append({
                "condition": f"'{gm}' validated in other scenarios",
                "missing": f"No validation in '{gs}'",
                "counterfactual": f"If '{gm}' were validated in '{gs}', gap resolved",
                "leaf": True,
            })
        for rec in related:
            lim = normalize_space(str(rec.get("limitation", "")))
            if lim and len(lim) > 15:
                branches.append({
                    "condition": f"Study: {trim_text(str(rec.get('title', '')), 80)}",
                    "missing": f"Limitation: {trim_text(lim, 150)}",
                    "counterfactual": limitation_specific_counterfactual(gap, lim, gm, gs),
                    "counterfactual_kind": "source_limitation_resolution_test",
                    "leaf": False,
                })
    else:
        # Fallback: synthesize counterfactual branches from gap_type and description
        if gt == "contradiction":
            branches.append({
                "condition": f"Conflicting claims about '{trim_text(desc, 80)}'",
                "missing": "No controlled experiment resolving the contradiction",
                "counterfactual": f"If a controlled experiment varied the disputed parameter in '{trim_text(gs or desc, 60)}', the contradiction would be resolved",
                "leaf": True,
            })
        elif gt in ("combinatorial", "density_hole"):
            branches.append({
                "condition": f"Method-scenario pair untested: '{trim_text(gm or desc, 60)}' in '{trim_text(gs or desc, 60)}'",
                "missing": "No validation study for this combination",
                "counterfactual": f"If '{trim_text(gm or 'the method', 40)}' were tested in '{trim_text(gs or 'the target scenario', 40)}', this density hole would be filled",
                "leaf": True,
            })
        elif gt == "migration":
            branches.append({
                "condition": f"Cross-domain transfer unvalidated",
                "missing": f"No study bridging the source and target domains in '{trim_text(desc, 80)}'",
                "counterfactual": f"If a transfer experiment validated the method across domains, this migration gap would be resolved",
                "leaf": True,
            })
        elif gt in ("improvement", "mechanism_problem"):
            branches.append({
                "condition": f"Mechanism unclear for '{trim_text(gm or desc, 60)}'",
                "missing": "No ablation or mechanistic study",
                "counterfactual": f"If an ablation study isolated the causal mechanism, this gap would be resolved",
                "leaf": True,
            })
        elif gt == "implicit_tabi":
            branches.append({
                "condition": f"TABI inference chain incomplete",
                "missing": "Warrant not empirically validated",
                "counterfactual": f"If the warrant linking the evidence pairs were tested, the implicit gap would be confirmed or refuted",
                "leaf": True,
            })
        # Always add a generic fallback branch for any gap type
        if not branches:
            branches.append({
                "condition": f"Gap: '{trim_text(desc, 100)}'",
                "missing": "No directly related evidence",
                "counterfactual": f"If a study addressed '{trim_text(desc, 60)}' directly, this gap would not exist",
                "leaf": True,
            })
    # Ingredients-based branches: concrete conditions from hypothesis_ingredients
    ingredients = gap.get("hypothesis_ingredients", {})
    for bound in (ingredients.get("numerical_bounds") or [])[:3]:
        branches.append({
            "condition": f"Test condition: {bound}",
            "missing": f"Not validated under {bound}",
            "counterfactual": f"If validated under {bound} conditions, this gap would be resolved",
            "leaf": True,
        })
    for metric in (ingredients.get("measurable_metrics") or [])[:3]:
        branches.append({
            "condition": f"Measurable metric: {metric}",
            "missing": f"{metric} not measured in current evidence",
            "counterfactual": f"If {metric} were measured and met threshold, this gap would be resolved",
            "leaf": True,
        })
    for cond in (ingredients.get("operating_conditions") or [])[:2]:
        branches.append({
            "condition": f"Operating condition: {cond}",
            "missing": f"Not tested under {cond}",
            "counterfactual": f"If tested under {cond} condition, this gap would be resolved",
            "leaf": True,
        })
    # Pre-built counterfactual_leaves from gap (if any)
    prebuilt_leaves = gap.get("counterfactual_leaves") or []
    for leaf_text in prebuilt_leaves[:3]:
        branches.append({
            "condition": trim_text(str(leaf_text), 120),
            "missing": "Pre-built counterfactual",
            "counterfactual": str(leaf_text),
            "leaf": True,
        })
    if gt in ("contradiction", "implicit_tabi"):
        tc = gap.get("tabi_chain", {})
        if tc:
            branches.append({
                "condition": f"Conflict: {trim_text(str(tc.get('shared_context', '')), 120)}",
                "missing": f"Warrant: {trim_text(str(tc.get('warrant', '')), 150)}",
                "counterfactual": "If controlled experiment resolved conflict, gap disappears",
                "leaf": True,
            })
    benchmarks = {normalize_space(str(r.get("benchmark", ""))).lower() for r in related if r.get("benchmark")}
    if benchmarks and gm:
        branches.append({
            "condition": f"Benchmarks: {', '.join(list(benchmarks)[:4])}",
            "missing": "No standardized benchmark",
            "counterfactual": "If standard benchmark existed, gap could be quantitatively assessed",
            "leaf": True,
        })
    leaves = [trim_text(b.get("counterfactual", ""), 200) for b in branches if b.get("leaf")]
    if not branches:
        root, cx = "No related evidence; gap may require entirely new research", "high"
    elif len(leaves) <= 1:
        root, cx = f"Single validation missing: {leaves[0] if leaves else desc[:100]}", "low"
    elif len(leaves) <= 3:
        root, cx = f"{len(leaves)} evidence conditions unmet", "medium"
    else:
        root, cx = f"{len(leaves)} evidence conditions unmet across dimensions", "high"
    return {
        "root": trim_text(root, 300),
        "branches": branches[:6],
        "leaf_conditions": leaves[:5],
        "resolution_complexity": cx,
        "related_evidence_count": len(related),
        "missing_evidence_count": len(missing),
        "gap_method": gm,
        "gap_scenario": gs,
    }


def limitation_specific_counterfactual(gap, limitation, method="", scenario=""):
    """Turn a source limitation into a gap-specific falsifiable condition.

    The old constant sentence (``If limitation addressed, evidence base
    strengthens``) contained no intervention, readout, or relation to the gap.
    This renderer preserves the source limitation while naming what evidence
    would actually change the status of the claim.
    """
    try:
        from ._intervention_ontology import classify_intervention_candidate
        from ._outcome_ontology import classify_outcome_candidate
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _intervention_ontology import classify_intervention_candidate
        from _outcome_ontology import classify_outcome_candidate
        from _utils import normalize_space, trim_text
    description = normalize_space(str(gap.get("description") or ""))
    limitation_text = normalize_space(str(limitation or ""))
    research_path = normalize_space(str(gap.get("suggested_research_path") or ""))
    ingredients = gap.get("hypothesis_ingredients", {}) if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    metrics = [str(item) for item in ingredients.get("measurable_metrics", []) if str(item).strip()]
    benchmarks = [str(item) for item in ingredients.get("benchmarks", []) if str(item).strip()]
    readout_candidates = metrics + benchmarks
    readout = next(
        (
            trim_text(value, 100)
            for value in readout_candidates
            if classify_outcome_candidate(
                value,
                target_outcome_terms=[],
                source_unit_ids=[],
                require_target_alignment=False,
                require_source_bound=False,
            ).get("ontology_valid")
        ),
        "a pre-specified mechanism-specific readout",
    )
    intervention_candidates = [
        *(
            ingredients.get("interventions", [])
            if isinstance(ingredients.get("interventions"), list)
            else []
        ),
        method,
    ]
    direct_intervention = next(
        (
            trim_text(str(value), 100)
            for value in intervention_candidates
            if classify_intervention_candidate(value).get("admissible_as_intervention")
        ),
        "",
    )
    intervention_clause = (
        f"the direct intervention '{direct_intervention}' were applied under a matched control"
        if direct_intervention
        else (
            "a source-grounded direct intervention were first defined for the causal factor in "
            f"'{trim_text(description or scenario, 100)}' and then applied under a matched control"
        )
    )
    limitation_lower = limitation_text.lower()
    if any(term in limitation_lower for term in ("mechanism", "causal", "mediate", "pathway", "unclear", "unknown")):
        return (
            f"If {intervention_clause} while {readout} and the proposed mediator were measured, "
            f"the study could support or falsify the unresolved mechanism in: '{trim_text(limitation_text, 130)}'."
        )
    if any(term in limitation_lower for term in ("sample", "cohort", "population", "single center", "small n", "generaliz")):
        return (
            f"If the claim in '{trim_text(description, 110)}' replicated in an independent, adequately powered population while measuring "
            f"{readout}, the sampling limitation '{trim_text(limitation_text, 120)}' would be resolved or confirmed as a boundary."
        )
    if any(term in limitation_lower for term in ("observational", "correlation", "association", "retrospective", "confound")):
        return (
            f"If {intervention_clause} while holding the named confounders constant, "
            f"a directional change in {readout} would distinguish causation from the limitation '{trim_text(limitation_text, 120)}'."
        )
    if research_path:
        return (
            f"If the source limitation '{trim_text(limitation_text, 110)}' were tested using '{trim_text(research_path, 120)}', "
            f"then {readout} would determine whether the gap claim '{trim_text(description, 100)}' is supported or falsified."
        )
    return (
        f"If a preregistered study directly tested '{trim_text(description, 120)}' against the source limitation "
        f"'{trim_text(limitation_text, 110)}', {readout} would determine whether the gap persists."
    )


def classify_gap_counterfactual_type(tree):
    if tree.get("related_evidence_count", 0) == 0:
        return "novel_concept_gap"
    return "complement_gap"


# ---------------------------------------------------------------------------
# Hypothesis Ingredients Extraction
# ---------------------------------------------------------------------------

def extract_hypothesis_ingredients(project, method, scenario, refs):
    """Extract domain-specific 'hypothesis raw materials' from PaperGraph records.

    Returns a dict with methods, scenarios, benchmarks, numerical_bounds,
    operating_conditions, and measurable_metrics — concrete parameters that
    MingLi can use to build non-template hypotheses.
    """
    try:
        from ._intervention_ontology import classify_intervention_candidate
        from ._outcome_ontology import classify_outcome_candidate
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _intervention_ontology import classify_intervention_candidate
        from _outcome_ontology import classify_outcome_candidate
        from _pipeline import project_records_for_mapping
        from _utils import normalize_space, unique_preserve_order

    method_role = classify_intervention_candidate(method)
    ingredients = {
        "methods": [method] if method and method_role.get("admissible_as_intervention") else [],
        "interventions": [method] if method and method_role.get("admissible_as_intervention") else [],
        "evidence_methods": [method] if method and method_role.get("category") == "epistemic_method" else [],
        "non_interventional_methods": [method] if method and not method_role.get("admissible_as_intervention") else [],
        "method_role_assessment": method_role,
        "scenarios": [scenario] if scenario else [],
        "benchmarks": [],
        "measurement_resources": [],
        "numerical_bounds": [],
        "operating_conditions": [],
        "measurable_metrics": [],
    }

    records = project_records_for_mapping(project)
    ml = normalize_space(method).lower() if method else ""
    sl = normalize_space(scenario).lower() if scenario else ""

    # Collect benchmarks from knowledge_map
    km = project.get("knowledge_map", {})
    msb = km.get("method_scenario_benchmark", {})
    for m_key, scenarios_map in msb.items():
        if ml and normalize_space(m_key).lower() == ml:
            for s_key, bench_map in scenarios_map.items():
                if isinstance(bench_map, dict):
                    ingredients["benchmarks"].extend(bench_map.keys())
                elif isinstance(bench_map, list):
                    ingredients["benchmarks"].extend(bench_map)

    # Extract numerical bounds, operating conditions, and metrics from related records
    numerical_re = re.compile(r"(\d+\.?\d*)\s*(kV|V|MW|GW|km|m|°C|℃|%|kPa|W/m2|MPa|GPa|kA|A|Hz|μs|ns|pC|dB)")
    condition_keywords = [
        "high-altitude", "extreme", "low-pressure", "high-temperature", "overload",
        "rated", "no-load", "short-circuit", "transient", "steady-state",
        "cold-start", "hot-spot", "partial-discharge", "full-load", "lightning",
    ]
    metric_keywords = [
        "flashover voltage", "electric field distortion", "partial discharge",
        "insulation resistance", "breakdown voltage", "corona loss",
        "efficiency", "stability", "temperature rise", "power factor",
        "dissipation factor", "withstand voltage", "impedance",
    ]

    related_records = []
    for r in records:
        rm = normalize_space(str(r.get("method", ""))).lower()
        rs = normalize_space(str(r.get("scenario", ""))).lower()
        if (ml and ml == rm) or (sl and sl == rs):
            related_records.append(r)
    # Fallback: if no exact match, use records whose method/scenario share tokens
    if not related_records:
        desc_tokens = set(re.findall(r"\w{4,}", f"{ml} {sl}"))
        for r in records:
            rec_tokens = set(re.findall(r"\w{4,}", f"{r.get('method', '')} {r.get('scenario', '')}".lower()))
            if desc_tokens & rec_tokens:
                related_records.append(r)

    for rec in related_records[:10]:
        text = " ".join([
            str(rec.get("abstract", "")),
            str(rec.get("conclusion", "")),
            str(rec.get("limitation", "")),
            str(rec.get("title", "")),
        ])
        # Numerical bounds
        for match in numerical_re.finditer(text):
            val, unit = match.group(1), match.group(2)
            ingredients["numerical_bounds"].append(f"{val}{unit}")
        # Operating conditions
        text_lower = text.lower()
        for cond in condition_keywords:
            if cond in text_lower:
                ingredients["operating_conditions"].append(cond)
        # Measurable metrics
        for metric in metric_keywords:
            if metric in text_lower:
                ingredients["measurable_metrics"].append(metric)

    # Deduplicate and cap
    valid_benchmarks: list[str] = []
    for benchmark in ingredients["benchmarks"]:
        role = classify_outcome_candidate(
            benchmark,
            target_outcome_terms=[],
            source_unit_ids=[],
            require_target_alignment=False,
            require_source_bound=False,
        )
        if role.get("ontology_valid"):
            valid_benchmarks.append(benchmark)
        else:
            ingredients["measurement_resources"].append(benchmark)
    ingredients["benchmarks"] = valid_benchmarks
    for key in ingredients:
        if isinstance(ingredients[key], list):
            ingredients[key] = unique_preserve_order(ingredients[key])[:5]

    return ingredients


def generate_counterfactual_leaves(method, scenario, refs):
    """Generate 'if X holds, gap disappears' leaf conditions."""
    try:
        from ._utils import trim_text, unique_preserve_order
    except ImportError:
        from _utils import trim_text, unique_preserve_order
    leaves = []
    m = str(method or "").strip()
    s = str(scenario or "").strip()
    if m and s:
        leaves.append(f"If '{m}' were validated in '{s}', this gap would not exist")
        leaves.append(f"If '{s}' had a standardized test benchmark, this gap could be directly assessed")
        leaves.append(f"If a published study confirmed '{m}' effectiveness in '{s}', the gap is resolved")
    if refs and isinstance(refs, list) and refs:
        leaves.append(f"If the method from '{trim_text(str(refs[0]), 80)}' were replicated in '{s}', this gap would be filled")
    if not leaves:
        leaves.append("If sufficient evidence were available, this gap would not exist")
    return unique_preserve_order(leaves)


# ---------------------------------------------------------------------------
# Multi-Gap Combination Selector
# ---------------------------------------------------------------------------

def select_gap_combination_for_hypothesis(project, ranked_gaps, strategy="auto"):
    """Select multiple gaps for aggregated hypothesis generation.

    Strategies:
    - 'auto': score by hypothesis_ingredients richness, pick top-3 with type diversity
    - 'top_k': pick top-3 by existing rank
    - 'complementary': pick one gap per distinct type
    """
    if not ranked_gaps:
        return []
    if len(ranked_gaps) <= 3:
        return list(ranked_gaps)

    if strategy == "top_k":
        return list(ranked_gaps[:3])

    if strategy == "complementary":
        selected, seen_types = [], set()
        for gap in ranked_gaps:
            gt = str(gap.get("gap_type", ""))
            if gt and gt not in seen_types:
                selected.append(gap)
                seen_types.add(gt)
                if len(selected) >= 3:
                    break
        # Fill remaining slots with top-ranked gaps
        for gap in ranked_gaps:
            if len(selected) >= 3:
                break
            if gap not in selected:
                selected.append(gap)
        return selected

    # 'auto': score by ingredient richness
    scored = []
    for gap in ranked_gaps:
        ingredients = gap.get("hypothesis_ingredients", {})
        score = 0
        score += len(ingredients.get("methods", [])) * 2
        score += len(ingredients.get("scenarios", [])) * 2
        score += len(ingredients.get("benchmarks", [])) * 1
        score += len(ingredients.get("numerical_bounds", [])) * 3
        score += len(ingredients.get("measurable_metrics", [])) * 2
        score += len(ingredients.get("operating_conditions", [])) * 2
        # Bonus for having supporting references
        score += len(gap.get("supporting_references", [])) * 1
        scored.append((score, gap))
    scored.sort(key=lambda x: -x[0])

    # Pick top-3 ensuring at least 2 different gap_types
    selected, types_seen = [], set()
    for _, gap in scored:
        if len(selected) >= 3:
            break
        selected.append(gap)
        types_seen.add(gap.get("gap_type", ""))
    # If all same type, swap last with first different type from remaining
    if len(types_seen) == 1 and len(scored) > 3:
        for _, gap in scored[3:]:
            if gap.get("gap_type", "") not in types_seen:
                selected[-1] = gap
                break
    return selected


# ---------------------------------------------------------------------------
# GRADE Pre-screening for Gap Combinations
# ---------------------------------------------------------------------------

def prefilter_gap_combination(project, gaps):
    """GRADE-style pre-screening: check if gap combination has enough literature support.

    Returns (sufficient: bool, reason: str, coverage: float).
    - coverage >= 0.6 → sufficient
    - 0.3 <= coverage < 0.6 → partially sufficient (proceed with warning)
    - coverage < 0.3 → insufficient (recommend supplement first)
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space

    all_refs = []
    all_descriptions = []
    for gap in gaps:
        refs = gap.get("supporting_references", [])
        if isinstance(refs, list):
            all_refs.extend(refs)
        desc = str(gap.get("description", ""))
        if desc:
            all_descriptions.append(desc)

    if not all_refs and not all_descriptions:
        return False, "Gap combination has no references and no descriptions", 0.0

    # Build corpus from PaperGraph records
    papergraph = project.get("papergraph", [])
    if not papergraph:
        return False, "PaperGraph is empty; need literature first", 0.0

    corpus_parts = []
    for record in papergraph:
        if isinstance(record, dict) and not _record_excluded_from_sh_gap_synthesis(record):
            corpus_parts.append(str(record.get("title", "")))
            corpus_parts.append(str(record.get("abstract", "")))
    corpus = " ".join(corpus_parts).lower()

    if not corpus.strip():
        return False, "PaperGraph records have no text content", 0.0

    # Check reference coverage
    covered = 0
    total = len(all_refs) if all_refs else 1
    for ref in all_refs:
        ref_key = normalize_space(str(ref)).lower()[:80]
        if ref_key and ref_key in corpus:
            covered += 1
    ref_coverage = covered / total if total > 0 else 0.0

    # Check description term coverage (GRADE-style)
    desc_terms = set(re.findall(r"\w{4,}", " ".join(all_descriptions).lower()))
    if desc_terms:
        term_hits = sum(1 for t in desc_terms if t in corpus)
        term_coverage = term_hits / len(desc_terms)
    else:
        term_coverage = 0.0

    # Combined coverage
    coverage = 0.5 * ref_coverage + 0.5 * term_coverage

    if coverage >= 0.6:
        return True, f"Coverage sufficient ({coverage:.0%})", coverage
    elif coverage >= 0.3:
        return True, f"Coverage partial ({coverage:.0%}), recommend supplement", coverage
    else:
        return False, f"Coverage insufficient ({coverage:.0%}), need literature supplement first", coverage


def infer_method_scenario_from_gap(gap, records):
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    dl = normalize_space(str(gap.get("description", ""))).lower()
    tabi = gap.get("tabi_chain", {})
    if tabi:
        sc = str(tabi.get("shared_context", ""))
        if "method=" in sc:
            m = sc.split("method=")[-1].split(",")[0].strip()
            s = sc.split("scenario=")[-1].split(",")[0].strip() if "scenario=" in sc else ""
            return m, s
    km = {
        normalize_space(str(r.get("method", ""))).lower()
        for r in records
        if r.get("method") and str(r.get("method", "")).lower() not in ("unknown", "unspecified")
    }
    ks = {
        normalize_space(str(r.get("scenario", ""))).lower()
        for r in records
        if r.get("scenario") and str(r.get("scenario", "")).lower() not in ("unknown", "unspecified")
    }
    mm = ms = ""
    for m in km:
        if m and m in dl:
            mm = m
            break
    for s in ks:
        if s and s in dl:
            ms = s
            break
    # Token-based fallback: if exact substring matching failed, score by shared significant words
    if not mm and km:
        desc_tokens = {t for t in re.findall(r"\w{4,}", dl)}
        best_score, best_method = 0, ""
        for m in km:
            m_tokens = {t for t in re.findall(r"\w{4,}", m)}
            overlap = len(desc_tokens & m_tokens)
            if overlap > best_score:
                best_score, best_method = overlap, m
        if best_score >= 1 and best_method:
            mm = best_method
    if not ms and ks:
        desc_tokens = {t for t in re.findall(r"\w{4,}", dl)}
        best_score, best_scenario = 0, ""
        for s in ks:
            s_tokens = {t for t in re.findall(r"\w{4,}", s)}
            overlap = len(desc_tokens & s_tokens)
            if overlap > best_score:
                best_score, best_scenario = overlap, s
        if best_score >= 1 and best_scenario:
            ms = best_scenario
    return mm, ms


def find_related_records(method, scenario, records):
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    ml = normalize_space(method).lower() if method else ""
    sl = normalize_space(scenario).lower() if scenario else ""
    return [
        r for r in records
        if (ml and normalize_space(str(r.get("method", ""))).lower() == ml)
        or (sl and normalize_space(str(r.get("scenario", ""))).lower() == sl)
    ][:8]


def find_missing_evidence(method, scenario, records):
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    ml = normalize_space(method).lower() if method else ""
    sl = normalize_space(scenario).lower() if scenario else ""
    missing = []
    pair_exists = any(
        normalize_space(str(r.get("method", ""))).lower() == ml
        and normalize_space(str(r.get("scenario", ""))).lower() == sl
        for r in records
    )
    if not pair_exists and ml and sl:
        missing.append(f"No record validates '{method}' in scenario '{scenario}'")
    return missing


# ---------------------------------------------------------------------------
# GRADE Knowledge Sufficiency
# ---------------------------------------------------------------------------

def grade_knowledge_sufficiency(hypothesis_text, project):
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_space
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import normalize_space
    records = project_records_for_mapping(project)
    if not records:
        return {
            "rank_ratio": 1.0,
            "verdict": "knowledge_insufficient",
            "knowledge_boundary": "outside",
            "covered_terms": [],
            "uncovered_terms": [],
            "suggested_action": "No records; import literature first",
        }
    corpus = " ".join(
        normalize_space(
            " ".join(str(r.get(k, "")) for k in ("title", "abstract", "method", "scenario", "contribution", "conclusion"))
        ).lower()
        for r in records
    )
    key_terms = extract_grade_key_terms(normalize_space(hypothesis_text).lower())
    if not key_terms:
        return {
            "rank_ratio": 0.0,
            "verdict": "knowledge_sufficient",
            "knowledge_boundary": "within",
            "covered_terms": [],
            "uncovered_terms": [],
            "suggested_action": "Proceed to verification",
        }
    covered = [t for t in key_terms if t in corpus]
    uncovered = [t for t in key_terms if t not in corpus]
    rr = len(uncovered) / max(1, len(key_terms))
    if rr < 0.3:
        v, b, a = "knowledge_sufficient", "within", "PaperGraph covers hypothesis well"
    elif rr < 0.6:
        v, b, a = "knowledge_partial", "boundary", f"Partial coverage; supplement: {', '.join(uncovered[:5])}"
    else:
        v, b, a = "knowledge_insufficient", "outside", f"Lacks coverage: {', '.join(uncovered[:5])}"
    return {
        "rank_ratio": round(rr, 3),
        "verdict": v,
        "knowledge_boundary": b,
        "covered_terms": covered[:10],
        "uncovered_terms": uncovered[:10],
        "total_key_terms": len(key_terms),
        "suggested_action": a,
    }


def extract_grade_key_terms(text):
    stopwords = {
        "the", "and", "for", "that", "this", "with", "from", "have", "been",
        "will", "are", "was", "were", "not", "but", "can", "may", "should",
        "when", "then", "than", "also", "more", "less", "such", "each",
        "which", "their", "there", "would", "could", "does", "into", "over",
        "under", "between", "through", "during", "before", "after", "above",
        "below", "because", "while", "where", "both", "either", "neither",
        "hypothesis", "study", "experiment", "method", "results", "show",
        "using", "based", "propose", "approach", "analysis", "paper",
    }
    words = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    filtered = [w for w in words if w not in stopwords and len(w) >= 4]
    bigrams = []
    for i in range(len(filtered) - 1):
        bg = f"{filtered[i]} {filtered[i+1]}"
        if len(bg) > 8:
            bigrams.append(bg)
    return list(dict.fromkeys(filtered + bigrams))[:20]

