"""Bounded, feedback-driven Survey search."""

from collections import Counter
from collections.abc import Mapping
import re

from .evidence_coverage_ledger import paper_identity
from .scientific_candidates import comparison_key, evidence_id, is_decision_candidate
from .survey_evidence_judgments import (
    contribution_failure, evidence_boundaries, failure_guidance, has_local_contribution, project_is_excluded,
)


CONTEXT_LEVELS = {"target_system", "source_system", "solution_class"}
ACTIONS = {"narrow_scope", "broaden_context", "resolve_name", "compare_alternative", "seek_counterevidence", "stop"}

OPENALEX_SEARCH_SEMANTICS = {
    "provider": "openalex",
    "unseparated_terms_operator": "AND",
    "alternative_operator": "OR",
    "recommended_english_word_range": [5, 14],
    "length_policy": "advisory_preserve_complete_names",
    "recommended_concept_groups": "one system_or_solution_class plus one search_purpose",
    "context_policy": "target_system_then_source_system_then_solution_class",
    "evaluation_policy": "assess_optional_conditions_after_retrieval",
}


def score(value):
    return value if type(value) is int and 0 <= value <= 5 else None


def canonical_query(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def recover_query_context_level(query, diagnostics=None):
    """Recover enum spelling without inferring a scientific context."""
    if not isinstance(query, Mapping):
        return query
    raw = query.get("context_level")
    if not isinstance(raw, str):
        return query
    normalized = raw.strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized not in CONTEXT_LEVELS or normalized == raw:
        return query
    result = dict(query)
    result["context_level_raw"] = raw
    result["context_level"] = normalized
    result["context_level_recovery"] = "normalize_context_enum"
    if diagnostics is not None:
        diagnostics.recovered("context_level", "normalize_context_enum")
    return result


def feedback_field_gaps(query, references):
    gaps = []
    if not isinstance(query.get("action"), str) or query["action"] not in ACTIONS - {"stop"}:
        gaps.append("action")
    if not isinstance(query.get("feedback_reason"), str) or not query["feedback_reason"].strip():
        gaps.append("feedback_reason")
    supplied = query.get("feedback_references")
    if not isinstance(supplied, list) or not any(isinstance(reference, str) and reference in references for reference in supplied):
        gaps.append("feedback_references")
    return gaps


def recover_feedback_fields(query, decisions, references):
    result = dict(query)
    identifier = query.get("query_id")
    if not isinstance(identifier, str) or not identifier:
        return result, []
    matches = []
    for decision in decisions:
        if decision.get("sub_hypothesis_id") != query.get("sub_hypothesis_id"):
            continue
        explicit_ids = decision.get("query_ids", [])
        if not isinstance(explicit_ids, list):
            explicit_ids = []
        explicit = decision.get("query_id") == identifier or identifier in explicit_ids
        has_explicit_ids = bool(decision.get("query_id") or explicit_ids)
        mentioned = re.search(r"(?<![\w.\-])" + re.escape(identifier) + r"(?![\w.\-])", str(decision.get("reason", "")))
        if explicit or (not has_explicit_ids and mentioned):
            matches.append(decision)
    if len(matches) != 1:
        return result, []
    decision = matches[0]
    replacements = {"action": decision.get("action"), "feedback_reason": decision.get("reason"),
                    "feedback_references": decision.get("references")}
    recovered = []
    for field in feedback_field_gaps(result, references):
        replacement = {**result, field: replacements[field]}
        if field not in feedback_field_gaps(replacement, references):
            result[field] = replacements[field]
            recovered.append(field)
    return result, recovered


def admit_query(raw, subhypotheses, topic, papers, *, feedback=False):
    if not isinstance(raw, Mapping):
        return None, "malformed_query"
    sh_id = raw.get("sub_hypothesis_id")
    sh = next((item for item in subhypotheses if item.get("sub_hypothesis_id") == sh_id), None)
    if sh is None:
        return None, "unknown_SH"
    if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in (
        "query_id", "query", "purpose", "context_reason", "expected_contribution")):
        return None, "missing_query_description"
    if not isinstance(raw.get("context_level"), str) or raw["context_level"] not in CONTEXT_LEVELS:
        return None, "invalid_context"
    scores = [score(raw.get(key)) for key in ("fit_score", "purpose_score", "context_score")]
    if None in scores:
        return None, "invalid_scores"
    fit, purpose, context = scores
    quality = 20 * (0.5 * fit + 0.25 * purpose + 0.25 * context)
    if quality < 70 or fit < 3 or context < 3:
        return None, "query_quality_below_threshold"
    if feedback and (not isinstance(raw.get("action"), str) or raw["action"] not in ACTIONS - {"stop"}
        or not isinstance(raw.get("feedback_reason"), str) or not raw["feedback_reason"].strip()
        or not isinstance(raw.get("feedback_references"), list)
        or not any(isinstance(reference, str) and reference.strip() for reference in raw["feedback_references"])):
        return None, "missing_feedback_justification"
    result = dict(raw)
    result.update(query=" ".join(raw["query"].split()), quality_score=quality)
    return result, "admitted"


def query_metrics(papers, sh_id, new_ids, provider_status):
    assessed, useful = [], []
    failures = Counter()
    local_counts, target_counts, ranking_counts, non_admission = Counter(), Counter(), Counter(), Counter()
    paper_diagnostics = []
    for paper in papers:
        project = paper.get("project_relevance", {})
        assessment = next((item for item in paper.get("sh_semantic_assessments", []) if item.get("sub_hypothesis_id") == sh_id), {})
        failure = "explicit_exclusion" if project_is_excluded(project) else contribution_failure(assessment)
        failures[failure] += 1
        boundaries = evidence_boundaries(assessment)
        local_counts[boundaries["local_contribution"]] += 1
        target_counts[boundaries["target_validation"]] += 1
        ranking_counts[boundaries["ranking_evidence"]] += 1
        admitted = failure == "local_contribution"
        if not admitted:
            non_admission[failure] += 1
        paper_diagnostics.append({"paper_id": paper_identity(paper), "admitted": admitted,
            "assessment_status": assessment.get("assessment_status", "assessment_unavailable"),
            "local_contribution": boundaries["local_contribution"], "target_validation": boundaries["target_validation"],
            "ranking_evidence": boundaries["ranking_evidence"], "non_admission_reason": None if admitted else failure,
            "review_status": assessment.get("local_contribution_review", {}).get("status", "not_requested")})
        if assessment.get("assessment_status") != "assessed":
            continue
        assessed.append(paper)
        if admitted:
            useful.append(paper)
    count = len(papers)
    valid = provider_status in {"success", "valid_empty"}
    precision = len(useful) / len(assessed) if assessed else None
    completion = len(assessed) / count if count else None
    novelty = sum(evidence_id(paper) in new_ids for paper in useful) / count if count else None
    hint = "provider_failure" if not valid else "broaden_context" if not count else "complete_assessment" if completion < 0.8 else "switch_uncovered_question" if precision >= 0.6 and novelty < 0.2 else "consider_contribution"
    revision = None
    if valid and not count:
        revision = {"reason": "valid_zero_results", "preferred_action": "broaden_context",
            "priority_order": ["reduce_intersection", "separate_alternatives_or_use_OR",
                "move_optional_conditions_to_post_retrieval", "broaden_context_preserving_purpose"],
            "scientific_absence_established": False}
    elif valid and assessed and completion >= 0.8:
        gaps = {key: value for key, value in failures.items() if key in {
            "identity_only", "no_local_contribution", "missing_evidence_spans", "insufficient_evidence"}}
        if not gaps:
            supported = [item for item in paper_diagnostics if item["admitted"]]
            target_gaps = sum(item["target_validation"] in {"indirect", "not_reported"} for item in supported)
            ranking_gaps = sum(item["ranking_evidence"] == "insufficient" for item in supported)
            gaps = {key: value for key, value in {"target_validation_gap": target_gaps,
                "ranking_evidence_gap": ranking_gaps}.items() if value}
        # Diagnose evidence shortages even when the current numerical score is low.
        # An unrelated majority may justify narrowing; it never rejects a candidate.
        unrelated = failures["irrelevant"] + failures["explicit_exclusion"]
        if gaps and (sum(gaps.values()) >= unrelated or precision >= 0.3):
            reason = max(gaps, key=gaps.get)
            revision = failure_guidance(reason)
            hint = reason
        elif len(assessed) >= 5 and precision < 0.3 and unrelated:
            reason = "irrelevant" if failures["irrelevant"] >= failures["explicit_exclusion"] else "explicit_exclusion"
            revision = failure_guidance(reason)
            hint = "narrow_scope"
    return {"returned_unique": count, "assessed": len(assessed), "useful": len(useful),
            "precision": precision, "assessment_completion": completion, "novelty": novelty,
            "provider_status": provider_status, "feedback_hint": hint, "revision_guidance": revision,
            "contribution_outcomes": dict(failures), "local_contribution_counts": dict(local_counts),
            "target_validation_counts": dict(target_counts), "ranking_evidence_counts": dict(ranking_counts),
            "non_admission_reasons": dict(non_admission), "paper_diagnostics": paper_diagnostics,
            "candidate_rejection_established": False}


def activate_candidates(registry, subhypotheses, limit=3, opportunity_limit=None):
    selected = {}
    for record in registry:
        record["active_status_by_subhypothesis"] = {sh_id: "relevant_holdout" if is_decision_candidate(record, sh_id) else "not_eligible"
            for sh_id in record["sub_hypothesis_ids"]}
    for sh in subhypotheses:
        sh_id = sh["sub_hypothesis_id"]
        candidates = sorted((record for record in registry if is_decision_candidate(record, sh_id)), key=lambda record: (
            record.get("candidate_relevance_by_subhypothesis", {}).get(sh_id) == "exploratory",
            -record.get("candidate_relevance_scores_by_subhypothesis", {}).get(sh_id, {}).get("weighted_score", 0), record["candidate_id"]))
        capacity = min(limit, opportunity_limit.get(sh_id, limit) if opportunity_limit is not None else limit)
        chosen = candidates[:1] if capacity else []
        if chosen and capacity >= 2:
            challenger = next((record for record in candidates[1:] if comparison_key(record) == comparison_key(chosen[0])), None)
            if challenger:
                chosen.append(challenger)
        chosen.extend(record for record in candidates if record not in chosen)
        chosen = chosen[:capacity]
        for record in chosen:
            record["active_status_by_subhypothesis"][sh_id] = "active"
        selected[sh_id] = [record["candidate_id"] for record in chosen]
        for rank, record in enumerate(chosen):
            record.setdefault("active_rank_by_subhypothesis", {})[sh_id] = rank
    return selected


def seed_assessments(paper):
    if project_is_excluded(paper.get("project_relevance", {})):
        return []
    return [item for item in paper.get("sh_semantic_assessments", []) if has_local_contribution(item)]


def bounded_seed_selection(papers, subhypotheses, registry, limit=40, minimum=2):
    eligible = []
    for paper in papers:
        project = paper.get("project_relevance", {})
        matches = seed_assessments(paper)
        if matches:
            local_score = max(score(item.get("semantic_relevance_score")) or 3 for item in matches)
            project_score = score(project.get("relevance_score"))
            paper["seed_priority"] = 20 * (0.4 * (project_score if project_score is not None else local_score) + 0.6 * local_score)
            eligible.append(paper)
    eligible.sort(key=lambda paper: (-paper["seed_priority"], evidence_id(paper)))
    selected, identities = [], set()
    counts = {sh["sub_hypothesis_id"]: 0 for sh in subhypotheses}

    def add(paper):
        if len(selected) >= limit or evidence_id(paper) in identities:
            return
        selected.append(paper)
        identities.add(evidence_id(paper))
        for item in seed_assessments(paper):
            sh_id = item["sub_hypothesis_id"]
            if sh_id in counts:
                counts[sh_id] += 1

    active_by_sh = {sh_id: sorted((record for record in registry if record.get("active_status_by_subhypothesis", {}).get(sh_id) == "active"),
        key=lambda record: record.get("active_rank_by_subhypothesis", {}).get(sh_id, 0)) for sh_id in counts}
    for rank in range(2):
        for sh_id, active in active_by_sh.items():
            if len(active) <= rank:
                continue
            sources = set(active[rank]["discovery_paper_ids"])
            if any(paper_identity(paper) in sources for paper in selected):
                continue
            source = next((paper for paper in eligible if paper_identity(paper) in sources and any(
                item.get("sub_hypothesis_id") == sh_id for item in seed_assessments(paper))), None)
            if source is not None:
                add(source)
    for _round in range(minimum):
        for sh_id in counts:
            paper = next((paper for paper in eligible if evidence_id(paper) not in identities and any(
                item.get("sub_hypothesis_id") == sh_id for item in seed_assessments(paper))), None)
            if paper is not None and counts[sh_id] < minimum:
                add(paper)
    for record in registry:
        if "active" not in record.get("active_status_by_subhypothesis", {}).values():
            continue
        sources = set(record["discovery_paper_ids"])
        if not any(paper_identity(paper) in sources for paper in selected):
            paper = next((paper for paper in eligible if paper_identity(paper) in sources), None)
            if paper is not None:
                add(paper)
    for paper in eligible:
        add(paper)
    evidence, exploration, context = [], [], []
    selected_object_ids = {id(paper) for paper in selected}
    for paper in papers:
        chosen = id(paper) in selected_object_ids
        assessments = seed_assessments(paper)
        roles = {item.get("recommended_graph_role", "undetermined") for item in assessments}
        kind = "evidence_seed" if "evidence_seed" in roles else "exploration_seed" if "exploration_seed" in roles else "context_seed"
        graph_allowed = bool(roles & {"evidence_seed", "exploration_seed"})
        graph_mode = "standard" if "evidence_seed" in roles else "bounded_exploration" if "exploration_seed" in roles else "do_not_expand" if "do_not_expand" in roles else "context_only" if "context_seed" in roles else "undetermined"
        paper["seed_selection"] = {"eligible": paper in eligible, "selected": chosen, "seed_kind": kind,
            "graph_expansion_eligible": chosen and graph_allowed, "graph_expansion_mode": graph_mode,
            "graph_role_assessment_status": "assessed" if roles - {"undetermined", None} else "undetermined",
            "semantic_assessment_ids": [item["sub_hypothesis_id"] for item in assessments],
            "decision_reason": "Bounded relevance and SH coverage selection" if chosen else "Outside bounded seed scope"}
        if chosen:
            (evidence if kind == "evidence_seed" else exploration if kind == "exploration_seed" else context).append(paper)
    return {"selected_papers": selected, "evidence_seed_papers": evidence, "exploration_seed_papers": exploration,
            "context_seed_papers": context, "holdout_candidates": [paper for paper in eligible if evidence_id(paper) not in identities],
            "rejected_papers": [paper for paper in papers if paper not in eligible], "allocation": {},
            "minimum_seed_papers_per_sh": minimum, "minimum_seed_counts_by_sh": counts,
            "minimum_seed_unmet_by_sh": {sh_id: minimum - count for sh_id, count in counts.items() if count < minimum},
            "effective_seed_budget": limit}


def comparison_metrics(ledger, subhypotheses, seed_counts, minimum=2):
    pairs, active, requested, assessed, pending = [], [], 0, 0, 0
    for record in ledger["records"]:
        for sh_id in record["sub_hypothesis_ids"]:
            status = record.get("candidate_relevance_by_subhypothesis", {}).get(sh_id)
            submitted = record.get("relevance_assessment_submitted_by_subhypothesis", {}).get(sh_id, True)
            requested += bool(submitted)
            assessed += bool(submitted) and status in {"relevant", "exploratory", "irrelevant", "background"}
            pending += status in {"unassessed", "assessment_unavailable", "deferred_budget"}
            if not is_decision_candidate(record, sh_id):
                continue
            cells = [cell for cell in record.get("minimum_evidence_matrix", {}).values() if cell["sub_hypothesis_id"] == sh_id and cell.get("required", True)]
            required_dimensions = ledger.get("dimensions_by_subhypothesis", {}).get(sh_id, [])
            base = sorted((dimension for dimension in required_dimensions if dimension.get("required", True)), key=lambda dimension: (
                not bool(dimension.get("screening_priority")), dimension.get("evidence_role") not in {"DIRECT_OBSERVATION", "DIRECT_COMPARATIVE_EVIDENCE"}))
            base_names = {base[0]["slot_name"]} if base else set()
            basic = any(cell["dimension"] in base_names and cell["requirement_satisfied"] for cell in cells)
            pairs.append(basic)
            if record.get("active_status_by_subhypothesis", {}).get(sh_id) == "active":
                opportunity = record.get("opportunity_by_subhypothesis", {}).get(sh_id) == "completed"
                active.append(basic or opportunity)
    coverage = sum(min(seed_counts.get(sh["sub_hypothesis_id"], 0) / minimum, 1) for sh in subhypotheses) / len(subhypotheses) if subhypotheses and minimum else None
    return {"sh_seed_coverage": coverage, "active_pairs": len(active), "all_relevant_pairs": len(pairs),
            "active_opportunity_coverage": sum(active) / len(active) if active else None,
            "all_candidate_base_evidence_coverage": sum(pairs) / len(pairs) if pairs else None,
            "relevance_assessment_completion": assessed / requested if requested else None,
            "relevance_assessment_requested_pairs": requested, "relevance_pending_pairs": pending,
            "relevant_holdout_pairs": len(pairs) - len(active)}


def calibration_metrics(labels, predictions):
    counts = Counter((bool(label), bool(prediction)) for label, prediction in zip(labels, predictions, strict=True))
    true_positive, false_positive, false_negative = counts[True, True], counts[False, True], counts[True, False]
    return {"true_positive": true_positive, "false_positive": false_positive, "false_negative": false_negative,
            "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
            "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None}
