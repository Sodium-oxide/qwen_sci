"""Grounded candidate registration and evidence-balanced Survey decisions.

Discovery establishes identities. Query hits establish retrieval history only.
Only grounded, dimension-specific assessments establish scientific evidence.
This module contains no domain-specific candidate names or evidence axes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any

from .evidence_coverage_ledger import paper_identity
from .paper_identity import canonical_paper_id
from .survey_evidence_judgments import normalize_evidence_boundaries, project_is_excluded


SCHEMA_VERSION = "scientific_candidate_ledger_v2"
OBJECT_ROLES = {"decision_candidate", "comparator", "target_system", "source_system_proxy",
                "mechanism_or_component", "background_entity", "role_unresolved"}
DECISION_ROLES = {"decision_candidate", "comparator"}


def normalize_candidate_role(value):
    return value if isinstance(value, str) and value in OBJECT_ROLES else "role_unresolved"


def candidate_role(record, sh_id):
    roles = record.get("roles_by_subhypothesis")
    roles = roles if isinstance(roles, Mapping) else {}
    return normalize_candidate_role(roles.get(sh_id, record.get("candidate_role", "decision_candidate")))


def candidate_relevance(record, sh_id):
    statuses = record.get("candidate_relevance_by_subhypothesis")
    if isinstance(statuses, Mapping) and sh_id in statuses:
        return text(statuses.get(sh_id)) or "unassessed"
    status = text(record.get("candidate_relevance_status"))
    return status or "unassessed"


def is_decision_candidate(record, sh_id=None):
    identifiers = [sh_id] if sh_id else record.get("sub_hypothesis_ids", [])
    return any(candidate_relevance(record, identifier) in {"unassessed", "relevant", "exploratory"}
               and candidate_role(record, identifier) in DECISION_ROLES
               and record.get("candidate_admission_by_subhypothesis", {}).get(identifier) not in {"excluded", "irrelevant"}
               and record.get("candidate_source_evidence_by_subhypothesis", {}).get(identifier, {}).get("status") not in {"excluded", "source_relevance_conflict"}
               for identifier in identifiers)


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return list(dict.fromkeys(text(item) for item in values if text(item)))


def normalized(value: Any) -> str:
    return text(value).casefold()


def mentions(alias: str, source: str) -> bool:
    return bool(alias and re.search(r"(?<!\w)" + re.escape(normalized(alias)) + r"(?!\w)", normalized(source)))


def evidence_id(paper: Mapping[str, Any]) -> str:
    # DOI/provider aliases represent one work across queries and SHs.
    doi = text(paper.get("doi") or (paper.get("externalIds") or {}).get("DOI"))
    if doi:
        return "doi:" + re.sub(r"^https?://(?:dx\.)?doi.org/", "", doi.casefold())
    return canonical_paper_id(paper_identity(paper))


def paper_text(paper: Mapping[str, Any]) -> str:
    from .source_context import source_texts
    return " ".join(str(value) for value in source_texts(paper).values())


def grounded_spans(raw: Any, paper: Mapping[str, Any], *, literal_verification=True) -> list[dict[str, str]]:
    from .source_context import source_texts
    sources = source_texts(paper)
    spans = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        source, quote = text(item.get("source")), text(item.get("text"))
        if source in sources and quote and sources[source]:
            if literal_verification and normalized(quote) not in normalized(sources[source]):
                continue
            span = {"source": source, "text": quote}
            if not literal_verification:
                span["verification_status"] = "model_semantic"
            spans.append(span)
    return spans


def register_candidates(
    observations: Sequence[Mapping[str, Any]],
    papers: Sequence[Mapping[str, Any]],
    *, literal_verification=True,
) -> list[dict[str, Any]]:
    """Merge explicit, source-grounded identities, never query terms or paper IDs."""
    by_id = {paper_identity(paper): paper for paper in papers}
    valid = []
    for raw in observations:
        name = text(raw.get("name") or raw.get("candidate_name"))
        pid = text(raw.get("paper_id"))
        paper = by_id.get(pid)
        spans = grounded_spans(raw.get("evidence_spans"), paper or {}, literal_verification=literal_verification)
        aliases = texts([name, *texts(raw.get("aliases"))])
        if not name or paper is None or not spans:
            continue
        # Identity must be visible in the supplied discovery source, not invented.
        if literal_verification:
            aliases = [alias for alias in aliases if mentions(alias, paper_text(paper))]
            if normalized(name) not in {normalized(alias) for alias in aliases}:
                continue
        sh_ids = texts(raw.get("sub_hypothesis_ids") or raw.get("sub_hypothesis_id"))
        if not sh_ids:
            sh_ids = texts([p.get("sub_hypothesis_id") for p in paper.get("retrieval_provenance", []) if isinstance(p, Mapping)])
        if not sh_ids:
            continue
        role = text(raw.get("candidate_role"))
        roles = raw.get("roles_by_subhypothesis") or {}
        roles = roles if isinstance(roles, Mapping) else {}
        valid.append({"name": name, "aliases": aliases, "paper_id": pid,
                      "sub_hypothesis_ids": sh_ids, "evidence_spans": spans,
                      "roles_by_subhypothesis": {sh: normalize_candidate_role(roles.get(sh, role)) for sh in sh_ids},
                      "role_reason": text(raw.get("role_reason")),
                      "taxonomic_level": text(raw.get("taxonomic_level") or raw.get("classification_level")) or "unspecified",
                      "candidate_kind": text(raw.get("candidate_kind")) or "scientific_object"})
    # Connected alias components make merging independent of observation order.
    components: list[list[dict[str, Any]]] = []
    for observation in sorted(valid, key=lambda item: (normalized(item["name"]), item["paper_id"])):
        keys = {normalized(alias) for alias in observation["aliases"]}
        matches = [group for group in components if
            (normalized(group[0]["candidate_kind"]), normalized(group[0]["taxonomic_level"])) ==
            (normalized(observation["candidate_kind"]), normalized(observation["taxonomic_level"]))
            and keys & {normalized(alias) for item in group for alias in item["aliases"]}]
        merged = [observation]
        for group in matches:
            merged.extend(group)
            components.remove(group)
        components.append(merged)
    records = []
    for group in components:
        names = sorted({item["name"] for item in group}, key=lambda value: (-len(value), normalized(value)))
        name = names[0]
        identity = " | ".join((normalized(name), normalized(group[0]["candidate_kind"]), normalized(group[0]["taxonomic_level"])))
        cid = "candidate_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        pids = sorted({item["paper_id"] for item in group})
        provenance = [p for pid in pids for p in by_id[pid].get("retrieval_provenance", []) if isinstance(p, Mapping)]
        role_sets = {sh: {item["roles_by_subhypothesis"][sh] for item in group if sh in item["roles_by_subhypothesis"]}
                     for sh in {sh for item in group for sh in item["sub_hypothesis_ids"]}}
        records.append({
            "candidate_id": cid, "name": name,
            "aliases": sorted({alias for item in group for alias in item["aliases"]}, key=normalized),
            "taxonomic_level": group[0]["taxonomic_level"], "candidate_kind": group[0]["candidate_kind"],
            "candidate_identity_status": "source_grounded" if literal_verification else "model_semantic",
            "sub_hypothesis_ids": sorted({sh for item in group for sh in item["sub_hypothesis_ids"]}),
            "roles_by_subhypothesis": {sh: next(iter(roles)) if len(roles) == 1 else "role_unresolved" for sh, roles in role_sets.items()},
            "candidate_relevance_by_subhypothesis": {sh: "unassessed" for sh in role_sets},
            "candidate_relevance_status": "unassessed",
            "role_reasons": texts([item["role_reason"] for item in group]),
            "discovery_paper_ids": pids,
            "discovery_queries": texts([p.get("query") for p in provenance]),
            "discovery_evidence_spans": [{"paper_id": item["paper_id"], **span} for item in group for span in item["evidence_spans"]],
            "hits_by_lane": {}, "evidence_dimensions": [], "retrieval_status": "unsearched",
            "admission_status": "unassessed", "seed_status": "not_selected", "comparator_group": "",
        })
    return sorted(records, key=lambda item: item["candidate_id"])


def normalize_evidence_assessment(
    raw: Mapping[str, Any], *, paper: Mapping[str, Any], candidate: Mapping[str, Any],
    sh_id: str, dimension: Mapping[str, Any],
) -> dict[str, Any]:
    semantic = candidate.get("candidate_identity_status") == "model_semantic"
    spans = grounded_spans(raw.get("evidence_spans"), paper, literal_verification=not semantic)
    identity_grounded = paper_identity(paper) in candidate.get("discovery_paper_ids", []) if semantic else any(mentions(alias, paper_text(paper)) for alias in candidate["aliases"])
    stance = text(raw.get("stance"))
    if stance not in {"supporting", "negative", "mixed", "neutral"}:
        stance = "neutral"
    scope = raw.get("scope_pass") is True
    role = raw.get("evidence_role_pass") is True
    minimum = raw.get("minimum_evidence_pass") is True
    project = paper.get("project_relevance") or {}
    excluded = isinstance(project, Mapping) and project_is_excluded(project)
    eligible = bool(identity_grounded and spans and scope and role and minimum and not excluded)
    return {
        "candidate_id": candidate["candidate_id"], "sub_hypothesis_id": sh_id,
        "dimension": dimension["slot_name"], "assessment_status": "assessed",
        "identity_grounded": identity_grounded, "scope_pass": scope,
        "evidence_role_pass": role, "minimum_evidence_pass": minimum,
        "eligible": eligible, "stance": stance, "evidence_spans": spans,
        "verification_status": "model_semantic" if semantic else "literal_source_verified",
        "reason": text(raw.get("reason")), "claim_limits": texts(raw.get("claim_limits")),
    }


def candidate_balance(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # Split credit for shared works; total weight equals unique effective works.
    owners: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for pid in record.get("effective_evidence_ids", []):
            owners[pid].add(record["candidate_id"])
    weights = {record["candidate_id"]: 0.0 for record in records}
    for candidate_ids in owners.values():
        for cid in candidate_ids:
            weights[cid] += 1.0 / len(candidate_ids)
    count, total = len(records), sum(weights.values())
    probabilities = [weight / total for weight in weights.values()] if total else [0.0] * count
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0)
    normalized_entropy = entropy / math.log(count) if count > 1 and total else 0.0
    gini = sum(abs(a - b) for a in weights.values() for b in weights.values()) / (2 * count * total) if count and total else 0.0
    normalized_gini = gini * count / (count - 1) if count > 1 else 0.0
    status = "no_effective_evidence" if not total else "single_candidate" if count < 2 else "concentrated" if normalized_gini >= 0.6 or normalized_entropy < 0.5 else "distributed"
    satisfied = sum(bool(record.get("minimum_evidence_satisfied")) for record in records)
    return {
        "registered_candidate_count": count, "minimum_evidence_satisfied_count": satisfied,
        "candidate_coverage": satisfied / count if count else 0.0,
        "minimum_evidence_matrix_coverage": satisfied / count if count else 0.0,
        "evidence_counts_by_candidate": {record["candidate_id"]: len(record.get("effective_evidence_ids", [])) for record in records},
        "effective_evidence_weights_by_candidate": weights, "unique_effective_evidence_count": len(owners),
        "evidence_concentration_entropy": entropy, "normalized_evidence_entropy": normalized_entropy,
        "evidence_concentration_gini": gini, "normalized_evidence_gini": normalized_gini,
        "evidence_concentration_status": status,
    }


def comparison_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return normalized(record.get("candidate_kind")), normalized(record.get("taxonomic_level"))


def build_candidate_ledger(
    registry: Sequence[Mapping[str, Any]], papers: Sequence[Mapping[str, Any]],
    dimensions_by_sh: Mapping[str, Sequence[Mapping[str, Any]]],
    query_lanes: Sequence[Mapping[str, Any]], summaries: Sequence[Mapping[str, Any]],
    *, selected_paper_ids: Sequence[str] = (), discovery_status: str = "completed",
) -> dict[str, Any]:
    by_id = {paper_identity(p): p for p in papers}
    lane_status = {}
    for summary in summaries:
        for lane_id, count in (summary.get("raw_candidates_by_lane") or {}).items():
            lane_status[lane_id] = {"status": "deferred_budget" if lane_id in summary.get("deferred_lanes", []) else "failed" if lane_id in summary.get("failed_lanes", []) else "searched_zero" if not count else "retrieved", "hit_count": count}
    query_statuses = [{"lane_id": lane["lane_id"], "query": lane.get("query", ""),
                      "candidate_id": lane.get("candidate_id", ""), "sub_hypothesis_id": lane.get("sub_hypothesis_id", ""),
                      "dimension": lane.get("evidence_dimension", ""), "alias_expansion": bool(lane.get("alias_expansion")),
                      "query_rewrite": bool(lane.get("query_rewrite")), "query_variant_id": lane.get("query_variant_id", ""),
                      "budget_phase": lane.get("budget_phase", ""),
                      **{key: value for key, value in lane.items() if key.startswith("discovery_")},
                      "context_expansion": bool(lane.get("context_expansion")),
                      "defer_reason": lane.get("defer_reason", ""),
                      "retrieval_stage": lane.get("retrieval_stage", ""),
                      **lane_status.get(lane["lane_id"], {"status": "unsearched", "hit_count": 0})}
                     for lane in query_lanes]
    selected = set(selected_paper_ids)
    records = []
    scope_ids, role_ids = set(), set()
    for source in registry:
        record = deepcopy(dict(source))
        cid = record["candidate_id"]
        queries = [q for q in query_statuses if q["candidate_id"] == cid]
        # Include independently discovered mentions, not just candidate query hits.
        related = [p for p in papers if (paper_identity(p) in record.get("discovery_paper_ids", [])
            if record.get("candidate_identity_status") == "model_semantic"
            else any(mentions(alias, paper_text(p)) for alias in record["aliases"]))]
        matrix = {}
        effective, negative, nonnegative, qualified_ids = set(), set(), set(), set()
        nonnegative_by_sh = defaultdict(set)
        for sh_id in record["sub_hypothesis_ids"]:
            if not is_decision_candidate(record, sh_id):
                continue
            for dimension in dimensions_by_sh.get(sh_id, []):
                name = dimension["slot_name"]
                assessments = [(p, a) for p in related for a in p.get("candidate_evidence_assessments", [])
                               if a.get("candidate_id") == cid and a.get("sub_hypothesis_id") == sh_id and a.get("dimension") == name]
                assessments = [(p, {**normalize_evidence_assessment(a, paper=p, candidate=record,
                    sh_id=sh_id, dimension=dimension), "assessment_status": a.get("assessment_status", "assessed")})
                    for p, a in assessments]
                accepted = [(p, a) for p, a in assessments if a.get("eligible") is True and a.get("assessment_status") == "assessed"]
                for p, a in assessments:
                    if a.get("scope_pass"):
                        scope_ids.add(evidence_id(p))
                    if a.get("scope_pass") and a.get("evidence_role_pass"):
                        role_ids.add(evidence_id(p))
                dimension_queries = [q for q in queries if q["sub_hypothesis_id"] == sh_id and q["dimension"] == name]
                statuses = {q["status"] for q in dimension_queries}
                unavailable = bool(assessments) and all(a.get("assessment_status") == "unavailable" for _, a in assessments)
                deferred = record.get("search_status_by_subhypothesis", {}).get(sh_id) == "deferred_budget" or any(
                    a.get("assessment_status") == "deferred_budget" for _, a in assessments) or record.get("assessment_status_by_subhypothesis", {}).get(sh_id) == "deferred_budget"
                status = "eligible" if accepted else "deferred_budget" if deferred or "deferred_budget" in statuses else "assessment_unavailable" if unavailable else "insufficient_evidence" if assessments else "retrieved_but_not_eligible" if "retrieved" in statuses else "failed" if "failed" in statuses or record.get("search_status_by_subhypothesis", {}).get(sh_id) == "failed" else "unsearched" if not statuses or "unsearched" in statuses else "searched_zero"
                pids = sorted({paper_identity(p) for p, a in accepted})
                negids = sorted({paper_identity(p) for p, a in accepted if a["stance"] in {"negative", "mixed"}})
                if accepted and all(a["stance"] == "negative" for _, a in accepted):
                    status = "negative_evidence"
                matrix[f"{sh_id}:{name}"] = {"sub_hypothesis_id": sh_id, "dimension": name,
                    "required": dimension.get("required", True), "status": status, "paper_ids": pids,
                    "minimum_independent_works": dimension.get("minimum_independent_works", 1),
                    "requirement_satisfied": len({evidence_id(p) for p, _assessment in accepted}) >= dimension.get("minimum_independent_works", 1),
                    "negative_paper_ids": negids, "query_lane_ids": [q["lane_id"] for q in dimension_queries]}
                effective.update(evidence_id(p) for p, a in accepted)
                qualified_ids.update(pids)
                negative.update(evidence_id(p) for p, a in accepted if a["stance"] == "negative")
                nonnegative.update(evidence_id(p) for p, a in accepted if a["stance"] != "negative")
                nonnegative_by_sh[sh_id].update(evidence_id(p) for p, a in accepted if a["stance"] != "negative")
        required = [cell for cell in matrix.values() if cell["required"]]
        complete = bool(required) and all(cell["requirement_satisfied"] for cell in required)
        query_states = {q["status"] for q in queries}
        retrieval_status = "deferred_budget" if "deferred_budget" in query_states or "deferred_budget" in record.get("search_status_by_subhypothesis", {}).values() else "retrieved" if any(q["hit_count"] for q in queries) else "failed" if "failed" in query_states else "unsearched" if not query_states or "unsearched" in query_states else "searched_zero"
        record.update({"paper_ids": sorted({paper_identity(p) for p in related}),
            "effective_evidence_ids": sorted(effective), "qualified_paper_ids": sorted(qualified_ids),
            "negative_evidence_ids": sorted(negative), "evidence_dimensions": list(matrix),
            "minimum_evidence_matrix": matrix, "minimum_evidence_satisfied": complete,
            "retrieval_status": retrieval_status,
            "admission_status": "negative_evidence" if effective and not nonnegative else "eligible" if complete else "insufficient_evidence" if effective else "retrieved_but_not_eligible" if related else retrieval_status,
            "seed_status": "selected" if selected & qualified_ids else "holdout" if effective else "rejected",
            "comparator_group": " | ".join(record["sub_hypothesis_ids"]),
            "hits_by_lane": {q["lane_id"]: q["hit_count"] for q in queries},
            "validation_queries": [q["query"] for q in queries],
            "fulltext_status": "fulltext_unavailable" if qualified_ids and all(by_id[pid].get("fulltext_status") == "fulltext_unavailable" for pid in qualified_ids) else "not_requested",
            "retrieval_budget": {"allocated_queries": len(queries), "executed_queries": sum(q["status"] != "unsearched" for q in queries), "failed_queries": sum(q["status"] == "failed" for q in queries)},
        })
        readiness = {}
        for sh_id in record["sub_hypothesis_ids"]:
            boundaries = normalize_evidence_boundaries(record.get("candidate_evidence_boundaries_by_subhypothesis", {}).get(sh_id))
            required_cells = [cell for cell in required if cell["sub_hypothesis_id"] == sh_id]
            missing = [cell["dimension"] for cell in required_cells if not cell["requirement_satisfied"]]
            applicable = is_decision_candidate(record, sh_id)
            sufficient = bool(required_cells) and not missing and bool(nonnegative_by_sh[sh_id])
            sufficient = sufficient and boundaries["ranking_evidence"] != "insufficient"
            readiness[sh_id] = {"evidence_status": "sufficient" if applicable and sufficient else "insufficient_evidence" if applicable else "not_applicable",
                "missing_dimensions": missing, "required_dimensions": [cell["dimension"] for cell in required_cells],
                "target_validation": boundaries["target_validation"], "validation_gaps": boundaries["validation_gaps"],
                "model_ranking_evidence": boundaries["ranking_evidence"], "ranking_eligible": False}
        record["ranking_readiness_by_subhypothesis"] = readiness
        if complete and record["seed_status"] != "selected" and record["admission_status"] == "eligible":
            record["admission_status"] = "eligible_but_not_selected"
        records.append(record)
    decision_records = [record for record in records if is_decision_candidate(record)]
    balance = candidate_balance(decision_records)
    groups = {}
    for sh_id in dimensions_by_sh:
        members = []
        for record in records:
            if sh_id not in record["sub_hypothesis_ids"] or not is_decision_candidate(record, sh_id):
                continue
            cells = [cell for cell in record["minimum_evidence_matrix"].values() if cell["sub_hypothesis_id"] == sh_id]
            required = [cell for cell in cells if cell["required"]]
            effective_ids = {evidence_id(by_id[pid]) for cell in cells for pid in cell["paper_ids"]}
            members.append({**record, "effective_evidence_ids": sorted(effective_ids),
            "minimum_evidence_satisfied": bool(required) and all(cell["requirement_satisfied"] for cell in required)})
        keys = {comparison_key(member) for member in members}
        comparable = len(keys) == 1 and all(kind not in {"", "scientific_object", "unspecified"}
            and level not in {"", "unspecified"} for kind, level in keys)
        groups[sh_id] = {**candidate_balance(members), "comparability_status": "same_kind_and_level" if comparable else "unresolved",
            "comparison_classes": [list(key) for key in sorted(keys)]}
    for record in records:
        applicable = []
        for sh_id, readiness in record["ranking_readiness_by_subhypothesis"].items():
            group = groups.get(sh_id, {})
            comparable = group.get("comparability_status") == "same_kind_and_level" and group.get("registered_candidate_count", 0) >= 2
            readiness["comparability_status"] = "comparable" if comparable else "insufficient_comparison"
            readiness["ranking_eligible"] = readiness["evidence_status"] == "sufficient" and comparable
            if readiness["evidence_status"] != "not_applicable":
                applicable.append(readiness["ranking_eligible"])
        record["ranking_eligible"] = bool(applicable) and all(applicable)
    discovery_queries = [q for q in query_statuses if q["retrieval_stage"] == "candidate_discovery"]
    discovery_retrieval_status = "degraded" if any(q["status"] in {"failed", "unsearched", "deferred_budget"} for q in discovery_queries) else "completed" if discovery_queries else "not_observed"
    sufficient = bool(groups) and discovery_status == "completed" and discovery_retrieval_status == "completed" and all(
        group["registered_candidate_count"] >= 2 and group["candidate_coverage"] == 1.0
        and group["comparability_status"] == "same_kind_and_level" for group in groups.values())
    screened = [(record, sh) for record in decision_records for sh in record["sub_hypothesis_ids"] if is_decision_candidate(record, sh)]
    screening_complete = sum(record.get("screening_status_by_subhypothesis", {}).get(sh) == "completed" for record, sh in screened)
    promoted = [(record, sh) for record, sh in screened if sh in record.get("promoted_subhypothesis_ids", [])]
    deep_complete = sum(all(cell["requirement_satisfied"] for cell in record["minimum_evidence_matrix"].values()
                            if cell["sub_hypothesis_id"] == sh and cell["required"]) for record, sh in promoted)
    staged = any("screening_status_by_subhypothesis" in record for record in decision_records)
    if staged:
        sufficient = sufficient and screening_complete == len(screened) and not any(
            value == "deferred_budget" for record in decision_records for value in record.get("search_status_by_subhypothesis", {}).values())
    unresolved_roles = sum(any(candidate_role(record, sh) == "role_unresolved"
        and candidate_relevance(record, sh) in {"unassessed", "relevant"}
        for sh in record["sub_hypothesis_ids"]) for record in records)
    relevance_pending = sum(any(candidate_relevance(record, sh) in {"assessment_unavailable", "deferred_budget"}
        for sh in record["sub_hypothesis_ids"]) for record in records)
    relevance_excluded = sum(bool(record["sub_hypothesis_ids"]) and all(candidate_relevance(record, sh) == "irrelevant"
        for sh in record["sub_hypothesis_ids"]) for record in records)
    ranking_gaps = any(readiness["model_ranking_evidence"] == "insufficient"
        for record in decision_records for readiness in record["ranking_readiness_by_subhypothesis"].values()
        if readiness["evidence_status"] != "not_applicable")
    sufficient = sufficient and not unresolved_roles and not relevance_pending and not ranking_gaps
    scope = {"discovered_objects": len(records), "decision_candidates": len(decision_records), "unresolved_roles": unresolved_roles,
             "relevance_excluded_objects": relevance_excluded, "relevance_pending_objects": relevance_pending,
             "screening_assignments": len(screened), "screening_completed": screening_complete,
             "screening_coverage": screening_complete / len(screened) if screened else 0.0,
             "promoted_assignments": len(promoted), "deep_comparison_completed": deep_complete,
             "deep_comparison_coverage": deep_complete / len(promoted) if promoted else 0.0,
            "deferred_candidates": sum("deferred_budget" in record.get("search_status_by_subhypothesis", {}).values()
                                       or "deferred_budget" in record.get("assessment_status_by_subhypothesis", {}).values() for record in decision_records)}
    return {
        "schema_version": SCHEMA_VERSION, "discovery_status": discovery_status, "discovery_retrieval_status": discovery_retrieval_status, "records": records,
        "dimensions_by_subhypothesis": deepcopy(dict(dimensions_by_sh)), "balance": balance,
        "balance_by_comparator_group": groups, "comparison_scope": scope, "comparison_status": "sufficient" if sufficient else "insufficient",
        "best_candidate_claim_allowed": sufficient and any(r["ranking_eligible"] for r in records), "query_statuses": query_statuses,
        "status_vocabulary": ["unsearched", "searched_zero", "failed", "retrieved_but_not_eligible",
            "eligible_but_not_selected", "fulltext_unavailable", "insufficient_evidence", "negative_evidence", "assessment_unavailable", "deferred_budget"],
        "funnel": {"raw_candidate_records": len(registry), "registered_scientific_candidates": len(records),
            "unique_papers_retrieved": len({evidence_id(p) for p in papers}),
            "hits_by_lane": {q["lane_id"]: q["hit_count"] for q in query_statuses},
            "synonym_expansion_hits": sum(q["hit_count"] for q in query_statuses if q["alias_expansion"]),
            "after_scope": len(scope_ids), "after_evidence_role": len(role_ids),
            "effective_evidence_papers": balance["unique_effective_evidence_count"],
            "selected_seed_records": sum(r["seed_status"] == "selected" for r in records),
            "holdout_records": sum(r["seed_status"] == "holdout" for r in records),
            "zero_result_queries": [q["lane_id"] for q in query_statuses if q["status"] == "searched_zero"],
            "failed_queries": [q["lane_id"] for q in query_statuses if q["status"] == "failed"],
            "unsearched_queries": [q["lane_id"] for q in query_statuses if q["status"] == "unsearched"],
            "deferred_queries": [q["lane_id"] for q in query_statuses if q["status"] == "deferred_budget"],
        },
    }


def freeze_candidate_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(ledger))
    result.pop("ledger_fingerprint", None)
    decision_records = [r for r in result["records"] if is_decision_candidate(r)]
    if result.get("retrieval_strategy") == "model_feedback":
        decision_records = [record for record in decision_records if record.get("root_seed_source_ids")
            and "active" in record.get("active_status_by_subhypothesis", {}).values()]
    complete = [r for r in decision_records if r["ranking_eligible"]]
    # Incomplete candidates stay exploration roots; they are never ranked as proven.
    roots = sorted(complete, key=lambda r: (-len(r["effective_evidence_ids"]), r["candidate_id"]))
    roots.extend(sorted((r for r in decision_records if not r["ranking_eligible"]), key=lambda r: (
        not bool(r.get("promoted_subhypothesis_ids")), -len(r["effective_evidence_ids"]), r["candidate_id"])))
    primary = roots[0] if roots else None
    challenger = next((r for r in roots[1:] if set(r["sub_hypothesis_ids"]) & set(primary["sub_hypothesis_ids"])
        and comparison_key(r) == comparison_key(primary)), None) if primary else None
    exploratory_challenger = False
    if primary and challenger is None:
        challenger = next((r for r in roots[1:] if set(r["sub_hypothesis_ids"]) & set(primary["sub_hypothesis_ids"])), None)
        exploratory_challenger = challenger is not None
    result["primary_candidate_id"] = primary["candidate_id"] if primary else ""
    result["challenger_candidate_ids"] = [challenger["candidate_id"]] if challenger else []
    result["challenger_records"] = [deepcopy(challenger)] if challenger else []
    result["challenger_status"] = "exploratory_comparability_unresolved" if exploratory_challenger else "retained" if challenger else "unavailable"
    result["frozen"] = True
    result["ledger_fingerprint"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def verify_candidate_ledger(ledger: Mapping[str, Any]) -> bool:
    if ledger.get("schema_version") != SCHEMA_VERSION or ledger.get("frozen") is not True:
        return False
    body = {key: value for key, value in ledger.items() if key != "ledger_fingerprint"}
    actual = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return actual == ledger.get("ledger_fingerprint")


def refresh_candidate_fulltext(ledger: Mapping[str, Any], acquisition: Mapping[str, Any]) -> dict[str, Any]:
    """Update acquisition observations without changing scientific admission."""
    result = deepcopy(dict(ledger))
    result.pop("ledger_fingerprint", None)
    by_id = {canonical_paper_id(pid): value for pid, value in acquisition.items() if isinstance(value, Mapping)}
    for record in result.get("records", []):
        states = {}
        for pid in record.get("paper_ids", []):
            value = by_id.get(canonical_paper_id(pid))
            if value is None:
                states[pid] = "not_requested"
            elif value.get("status") == "metadata_only_by_fulltext_budget":
                states[pid] = "not_requested_by_budget"
            elif value.get("fulltext_available") is True:
                states[pid] = "available"
            elif value.get("status") in {"pending", "queued", "in_progress", "not_requested"}:
                states[pid] = str(value["status"])
            else:
                states[pid] = "fulltext_unavailable"
        record["fulltext_status_by_paper"] = states
        values = set(states.values())
        record["fulltext_status"] = "available" if "available" in values else "fulltext_unavailable" if "fulltext_unavailable" in values else "pending" if values & {"pending", "queued", "in_progress"} else "not_requested_by_budget" if values == {"not_requested_by_budget"} else "not_requested"
    return freeze_candidate_ledger(result)
