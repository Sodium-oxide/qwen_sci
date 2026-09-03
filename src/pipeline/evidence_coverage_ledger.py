"""Slot-level evidence association, coverage ledger, and seed selection.

The ledger records whether each required research-question slot has admissible
evidence. It never converts retrieval provenance, a topical match, or a review
paper into support for a substantive conclusion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION = "evidence_coverage_ledger_v1"
_SCOPE_TEXT_KEYS = ("contexts", "study_designs")
_SCOPE_VALUE_KEYS = ("languages", "publication_types", "providers", "source_types")
_PROJECT_STOPWORDS = frozenset(
    {"and", "for", "from", "into", "the", "with", "using", "use", "based", "study", "research"}
)
_EVIDENCE_TYPE_TERMS = {
    "primary_experiment": ("experiment", "experimental", "trial", "field study", "controlled study"),
    "observational_study": ("observational", "cohort", "cross sectional", "survey study"),
    "benchmark": ("benchmark", "evaluation", "comparative evaluation", "comparison"),
    "deployment_evaluation": ("deployment", "real world", "field evaluation"),
    "mechanistic_study": ("mechanism", "mechanistic", "pathway"),
    "ablation": ("ablation", "ablate"),
    "failure_analysis": ("failure", "limitation", "adverse", "reversal", "error analysis"),
    "negative_result": ("negative result", "no effect", "ineffective", "false negative"),
    "review": ("review", "overview"),
    "systematic_review": ("systematic review", "scoping review"),
    "meta_analysis": ("meta-analysis", "meta analysis"),
}
_ROLE_EVIDENCE_TYPES = {
    "DIRECT_OBSERVATION": {"primary_experiment", "observational_study", "deployment_evaluation"},
    "COMPARATIVE_OR_MEASUREMENT_EVIDENCE": {"primary_experiment", "observational_study", "benchmark", "deployment_evaluation"},
    "MECHANISTIC_EVIDENCE": {"mechanistic_study", "ablation"},
    "LIMITING_OR_CHALLENGING_EVIDENCE": {"failure_analysis", "negative_result", "observational_study"},
    "BACKGROUND_CONTEXT": {"review", "systematic_review", "meta_analysis"},
}
_COMPARABILITY_SLOT_SETS = {
    "COMPARATIVE_EVALUATION": ("candidate", "comparator", "comparison_condition", "comparable_endpoint"),
    "BOUNDARY_HETEROGENEITY": ("base_relation", "boundary_variable", "condition_a", "condition_b", "comparable_endpoint"),
    "REPLICATION_CONTRADICTION": ("shared_claim", "result_a", "result_b", "comparability_axes"),
    "GENERALIZATION_TRANSPORT": ("source_system", "target_system", "shift_or_variation", "external_validation"),
}
_MEASUREMENT_SLOT_SETS = {
    "MEASUREMENT_VALIDITY": ("construct", "proxy_or_measure", "reference_or_target_measure", "mapping_or_calibration"),
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = re.sub(r"\s+", " ", str(item or "").strip())[:240]
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _normalized(value: Any) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "").casefold()).split())


def _contains(text: str, term: str) -> bool:
    normalized_term = _normalized(term)
    return bool(normalized_term and normalized_term in text)


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def paper_identity(paper: Mapping[str, Any]) -> str:
    for key in ("openalex_id", "paperId", "paper_id", "doi"):
        value = str(paper.get(key) or "").strip()
        if value:
            return value
    external_ids = _mapping(paper.get("externalIds"))
    for key in ("DOI", "doi", "ArXiv", "arXiv"):
        value = str(external_ids.get(key) or "").strip()
        if value:
            return value
    return re.sub(r"\W+", "", str(paper.get("title") or "").casefold()) or "unknown-paper"


def _paper_text(paper: Mapping[str, Any]) -> str:
    return _normalized(" ".join(str(paper.get(key) or "") for key in ("title", "abstract", "venue")))


def _paper_year(paper: Mapping[str, Any]) -> int | None:
    for key in ("year", "publication_year", "publication_date", "date"):
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", str(paper.get(key) or ""))
        if match:
            return int(match.group(1))
    return None


def _year_ranges(values: Sequence[str]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for value in values:
        years = [int(year) for year in re.findall(r"\b(?:18|19|20|21)\d{2}\b", value)]
        if len(years) == 1:
            result.append((years[0], years[0]))
        elif len(years) >= 2:
            result.append((min(years[0], years[1]), max(years[0], years[1])))
    return result


def _paper_scope_value(paper: Mapping[str, Any], key: str) -> str:
    if key == "providers":
        return str(paper.get("api_platform") or paper.get("provider") or "").strip()
    if key == "source_types":
        provider = str(paper.get("api_platform") or paper.get("provider") or "").strip().casefold()
        if provider == "arxiv":
            return "preprint"
        value = str(paper.get("source_type") or paper.get("publication_type") or paper.get("type") or "").strip()
        return value or ("indexed_work" if provider else "")
    if key == "languages":
        return str(paper.get("language") or paper.get("lang") or "").strip()
    return str(paper.get("publication_type") or paper.get("type") or "").strip()


def _scope_assessment(
    paper: Mapping[str, Any],
    paper_text: str,
    allowed_scope: Mapping[str, Any],
    excluded_scope: Mapping[str, Any],
) -> dict[str, list[str]]:
    allowed_matches: list[str] = []
    violations: list[str] = []
    unverified: list[str] = []
    allowed = _mapping(allowed_scope)
    excluded = _mapping(excluded_scope)

    allowed_ranges = _year_ranges(_texts(allowed.get("date_range"), limit=8))
    excluded_ranges = _year_ranges(_texts(excluded.get("date_range"), limit=8))
    if _texts(allowed.get("date_range"), limit=8):
        year = _paper_year(paper)
        if not allowed_ranges or year is None:
            unverified.append("allowed_date_range")
        elif any(start <= year <= end for start, end in allowed_ranges):
            allowed_matches.append(f"date_range:{year}")
        else:
            violations.append(f"allowed_date_range:{year}")
    if _texts(excluded.get("date_range"), limit=8):
        year = _paper_year(paper)
        if not excluded_ranges or year is None:
            unverified.append("excluded_date_range")
        elif any(start <= year <= end for start, end in excluded_ranges):
            violations.append(f"excluded_date_range:{year}")

    for key in _SCOPE_VALUE_KEYS:
        allowed_values = _texts(allowed.get(key), limit=8)
        excluded_values = _texts(excluded.get(key), limit=8)
        raw_value = _paper_scope_value(paper, key)
        paper_value = _normalized(raw_value)
        if allowed_values:
            if not paper_value:
                unverified.append(f"allowed_{key}")
            elif any(_contains(paper_value, value) or _contains(_normalized(value), paper_value) for value in allowed_values):
                allowed_matches.append(f"{key}:{raw_value}")
            else:
                violations.append(f"allowed_{key}:{raw_value}")
        if excluded_values and not paper_value:
            unverified.append(f"excluded_{key}")
        elif paper_value and any(_contains(paper_value, value) or _contains(_normalized(value), paper_value) for value in excluded_values):
            violations.append(f"excluded_{key}:{raw_value}")

    for key in _SCOPE_TEXT_KEYS:
        allowed_values = _texts(allowed.get(key), limit=8)
        excluded_values = _texts(excluded.get(key), limit=8)
        if allowed_values:
            matches = [value for value in allowed_values if _contains(paper_text, value)]
            if matches:
                allowed_matches.extend(f"{key}:{value}" for value in matches)
            else:
                unverified.append(f"allowed_{key}")
        excluded_matches = [value for value in excluded_values if _contains(paper_text, value)]
        violations.extend(f"excluded_{key}:{value}" for value in excluded_matches)
        if excluded_values and not excluded_matches and not str(paper.get("abstract") or "").strip():
            unverified.append(f"excluded_{key}")
    if _texts(allowed.get("notes"), limit=8):
        unverified.append("allowed_notes")
    excluded_notes = _texts(excluded.get("notes"), limit=8)
    note_matches = [note for note in excluded_notes if _contains(paper_text, note)]
    violations.extend(f"excluded_notes:{note}" for note in note_matches)
    if excluded_notes and not note_matches:
        unverified.append("excluded_notes")
    return {
        "allowed_matches": _unique(allowed_matches),
        "violations": _unique(violations),
        "unverified": _unique(unverified),
    }


def _confirmed_evidence_types(paper_text: str) -> list[str]:
    return [
        evidence_type
        for evidence_type, terms in _EVIDENCE_TYPE_TERMS.items()
        if any(_contains(paper_text, term) for term in terms)
    ]


def _confirmed_evidence_roles(evidence_types: Sequence[str]) -> list[str]:
    values = set(evidence_types)
    return [
        role
        for role, accepted_types in _ROLE_EVIDENCE_TYPES.items()
        if values & accepted_types
    ]


def _task_provenance(paper: Mapping[str, Any], task_id: str) -> list[dict[str, Any]]:
    records = paper.get("retrieval_provenance")
    if not isinstance(records, list):
        return []
    matches: list[dict[str, Any]] = []
    for record in records:
        item = _mapping(record)
        if not item:
            continue
        if item.get("slot_recovery_task_id") == task_id:
            matches.append(item)
            continue
        recovered_task_ids = _texts(item.get("recovered_slot_task_ids"), limit=20)
        if task_id in recovered_task_ids:
            matches.append(item)
    return matches


def _llm_slot_contribution(
    semantic_assessment: Mapping[str, Any],
    slot_name: str,
) -> dict[str, str]:
    """Return the LLM's contribution classification for one optional SH slot."""

    for raw in semantic_assessment.get("candidate_slot_contributions", []):
        item = _mapping(raw)
        if item.get("slot_name") != slot_name:
            continue
        support_level = str(item.get("support_level") or "none").casefold()
        if support_level in {"direct", "partial", "indirect", "none"}:
            return {
                "support_level": support_level,
                "reason": str(item.get("reason") or ""),
            }
    return {"support_level": "none", "reason": ""}


def _heuristic_slot_match_score(
    *,
    provenance: Sequence[Mapping[str, Any]],
    matched_concepts: Sequence[str],
    expected_role: str,
    keyword_roles: Sequence[str],
) -> tuple[int, list[str]]:
    """Summarize literal retrieval signals without turning them into SH relevance."""

    signals: list[str] = []
    if provenance:
        signals.append("retrieved_for_slot")
    if matched_concepts:
        signals.append("literal_concept_match")
    if expected_role and expected_role in keyword_roles:
        signals.append("keyword_evidence_role_match")
    return len(signals), signals


def _slot_assessment(
    paper: Mapping[str, Any],
    *,
    paper_text: str,
    task: Mapping[str, Any],
    exclusion_violations: Sequence[str],
    semantic_assessment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    definition = _mapping(task.get("slot_definition"))
    concepts = _texts(definition.get("retrieval_concepts"), limit=10)
    matched_concepts = [term for term in concepts if _contains(paper_text, term)]
    provenance = _task_provenance(paper, task_id)
    evidence_types = _confirmed_evidence_types(paper_text)
    confirmed_roles = _confirmed_evidence_roles(evidence_types)
    expected_role = str(task.get("expected_evidence_role") or "")
    semantic = _mapping(semantic_assessment)
    llm_slot = _llm_slot_contribution(
        semantic,
        str(task.get("slot_name") or ""),
    )
    heuristic_score, heuristic_signals = _heuristic_slot_match_score(
        provenance=provenance,
        matched_concepts=matched_concepts,
        expected_role=expected_role,
        keyword_roles=confirmed_roles,
    )
    scope = _scope_assessment(
        paper,
        paper_text,
        _mapping(task.get("allowed_evidence_scope")),
        _mapping(task.get("excluded_evidence_scope")),
    )
    scope_ok = not scope["violations"] and not scope["unverified"]
    background_only = bool(
        provenance
        and matched_concepts
        and "BACKGROUND_CONTEXT" in confirmed_roles
        and expected_role != "BACKGROUND_CONTEXT"
    )
    evidence_role_confirmed = expected_role in confirmed_roles
    heuristic_status = (
        "EXCLUDED"
        if exclusion_violations
        else "OUT_OF_SCOPE_OR_UNVERIFIED"
        if not scope_ok
        else "NOT_RETRIEVED_FOR_SLOT"
        if not provenance
        else "INSUFFICIENT_SLOT_MATCH"
        if not matched_concepts
        else "BACKGROUND_ONLY"
        if background_only
        else "INSUFFICIENT_EVIDENCE_ROLE"
        if not evidence_role_confirmed
        else "COVERED"
    )

    # Without an LLM result retain the legacy coverage ledger behavior for
    # offline/backward-compatible runs. Once semantic assessment exists, its
    # contribution type—not literal slot wording—determines the evidence state.
    if not semantic:
        status = heuristic_status
        admission_status = (
            "DIRECT_EVIDENCE" if status == "COVERED" else "NOT_DIRECT_EVIDENCE"
        )
        graph_value_status = "UNASSESSED"
    elif exclusion_violations or semantic.get("explicit_exclusion_matches"):
        status = "EXCLUDED"
        admission_status = "BLOCKED_BY_EXCLUSION"
        graph_value_status = "REJECTED"
    elif scope["violations"]:
        status = "OUT_OF_SCOPE"
        admission_status = "SCOPE_LIMITED"
        graph_value_status = (
            "EXPAND" if semantic.get("recommended_graph_role") != "do_not_expand" else "HOLDOUT"
        )
    elif scope["unverified"]:
        status = "SCOPE_UNVERIFIED"
        admission_status = "SCOPE_UNCERTAIN"
        graph_value_status = (
            "EXPAND" if semantic.get("recommended_graph_role") != "do_not_expand" else "HOLDOUT"
        )
    elif llm_slot["support_level"] == "direct" and semantic.get("evidence_spans"):
        status = "COVERED"
        admission_status = "DIRECT_EVIDENCE"
        graph_value_status = "EXPAND"
    elif semantic.get("overall_relation") == "background":
        status = "BACKGROUND_ONLY"
        admission_status = "BACKGROUND_CONTEXT_ONLY"
        graph_value_status = "CONTEXT"
    elif llm_slot["support_level"] in {"partial", "indirect"} or semantic.get(
        "overall_relation"
    ) in {"partial", "indirect", "boundary", "counterevidence", "method", "hypothesis_generating"}:
        status = "PARTIAL_OR_INDIRECT_EVIDENCE"
        admission_status = "PARTIAL_OR_INDIRECT_ONLY"
        graph_value_status = (
            "EXPAND" if semantic.get("recommended_graph_role") != "do_not_expand" else "HOLDOUT"
        )
    elif semantic.get("overall_relation") == "irrelevant":
        status = "IRRELEVANT"
        admission_status = "NOT_DIRECT_EVIDENCE"
        graph_value_status = "REJECTED"
    else:
        status = "UNCERTAIN"
        admission_status = "INSUFFICIENT_FOR_DIRECT_CLAIM"
        graph_value_status = "HOLDOUT"
    return {
        "task_id": task_id,
        "slot_name": str(task.get("slot_name") or ""),
        "expected_evidence_role": expected_role,
        "minimum_evidence": str(task.get("minimum_evidence") or ""),
        "admission_rule": str(task.get("admission_rule") or ""),
        "matched_concepts": matched_concepts,
        "retrieval_provenance": provenance,
        "heuristic_slot_match_score": heuristic_score,
        "heuristic_signals": heuristic_signals,
        "confirmed_evidence_types": evidence_types,
        "confirmed_evidence_roles": confirmed_roles,
        "keyword_inferred_evidence_roles": confirmed_roles,
        "heuristic_coverage_status": heuristic_status,
        "llm_semantic_support_level": llm_slot["support_level"],
        "llm_slot_contribution_reason": llm_slot["reason"],
        "llm_contribution_types": list(semantic.get("contribution_types") or []),
        "llm_evidence_spans": list(semantic.get("evidence_spans") or []),
        "llm_claim_limits": list(semantic.get("claim_limits") or []),
        "scope_assessment": scope,
        "coverage_status": status,
        "admission_status": admission_status,
        "graph_value_status": graph_value_status,
        "covered": status == "COVERED",
        "background_only": status == "BACKGROUND_ONLY",
    }


def _semantic_assessment_for_subhypothesis(
    paper: Mapping[str, Any],
    sub_hypothesis_id: str,
) -> dict[str, Any]:
    """Return the LLM paper-to-SH assessment, if this collection run made one."""

    for raw in paper.get("sh_semantic_assessments", []):
        assessment = _mapping(raw)
        if assessment.get("sub_hypothesis_id") == sub_hypothesis_id:
            return assessment
    return {}


def _semantic_assessment_is_seed_candidate(
    assessment: Mapping[str, Any],
    *,
    threshold: int,
) -> bool:
    """Use LLM contribution semantics, not slot-count heuristics, for seed candidacy."""

    if not assessment or assessment.get("assessment_status") != "assessed":
        return False
    if assessment.get("overall_relation") == "irrelevant":
        return False
    if assessment.get("recommended_graph_role") == "do_not_expand":
        return False
    if assessment.get("explicit_exclusion_matches"):
        return False
    try:
        return int(assessment.get("semantic_relevance_score") or 0) >= threshold
    except (TypeError, ValueError):
        return False


def associate_papers_with_subhypotheses(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    project_fingerprint: str = "",
    relevance_threshold: int = 3,
    max_slots_per_paper: int = 2,
) -> list[dict[str, Any]]:
    """Attach retrieval/coverage facts and LLM SH semantics without slot-count scoring."""

    del max_slots_per_paper
    sh_list = [
        _mapping(item)
        for item in subhypotheses or []
        if isinstance(item, Mapping)
        and _mapping(item).get("sub_hypothesis_id")
        and _mapping(item).get("retrieval_strategy") == "slot_driven_required_slot_recovery"
    ]
    output: list[dict[str, Any]] = []
    for original in papers or []:
        if not isinstance(original, Mapping):
            continue
        paper = dict(original)
        paper_text = _paper_text(paper)
        sh_matches: list[dict[str, Any]] = []
        aggregate_slots: list[dict[str, str]] = []
        aggregate_provenance: list[dict[str, Any]] = []
        aggregate_roles: list[str] = []
        for sh in sh_list:
            exclusions = _texts(sh.get("exclusion_terms"), limit=10)
            exclusion_violations = [term for term in exclusions if _contains(paper_text, term)]
            sub_hypothesis_id = str(sh.get("sub_hypothesis_id") or "")
            semantic_assessment = _semantic_assessment_for_subhypothesis(
                paper,
                sub_hypothesis_id,
            )
            assessments = [
                _slot_assessment(
                    paper,
                    paper_text=paper_text,
                    task=_mapping(task),
                    exclusion_violations=exclusion_violations,
                    semantic_assessment=semantic_assessment,
                )
                for task in sh.get("slot_recovery_tasks", [])
                if isinstance(task, Mapping)
            ]
            covered = [item for item in assessments if item["covered"]]
            confirmed_roles = _unique(
                [role for item in assessments for role in item["confirmed_evidence_roles"]]
            )
            potential_slots = [item["slot_name"] for item in covered]
            provenance = [
                record
                for item in assessments
                for record in item["retrieval_provenance"]
            ]
            semantic_seed_candidate = _semantic_assessment_is_seed_candidate(
                semantic_assessment,
                threshold=relevance_threshold,
            )
            match = {
                "sub_hypothesis_id": sub_hypothesis_id,
                "question_kind": str(sh.get("question_kind") or ""),
                "semantic_assessment": semantic_assessment,
                "semantic_seed_candidate": semantic_seed_candidate,
                "violated_exclusions": exclusion_violations,
                "slot_assessments": assessments,
                "confirmed_evidence_roles": confirmed_roles,
                "evidence_roles": confirmed_roles,
                "coverage_slots": potential_slots,
                "potential_coverage_slots": potential_slots,
                "allocated_coverage_slots": [],
                "slot_provenance": provenance,
                "research_context_fingerprint": project_fingerprint,
                "semantic_seed_candidate_reason": (
                    "excluded"
                    if exclusion_violations or semantic_assessment.get("explicit_exclusion_matches")
                    else "llm_semantic_assessment_unavailable"
                    if not semantic_assessment
                    else "not_recommended_for_graph_expansion"
                    if not semantic_seed_candidate
                    else ""
                ),
            }
            sh_matches.append(match)
            if covered:
                aggregate_roles = _unique([*aggregate_roles, *confirmed_roles])
                for slot in potential_slots:
                    pair = {"sub_hypothesis_id": match["sub_hypothesis_id"], "slot": slot}
                    if pair not in aggregate_slots:
                        aggregate_slots.append(pair)
                for record in provenance:
                    if record not in aggregate_provenance:
                        aggregate_provenance.append(record)
        paper["sh_matches"] = sh_matches
        paper["evidence_roles"] = aggregate_roles
        paper["coverage_slots"] = aggregate_slots
        paper["slot_provenance"] = aggregate_provenance
        output.append(paper)
    return output


def _assessment_for_slot(match: Mapping[str, Any], slot_name: str) -> dict[str, Any] | None:
    for assessment in match.get("slot_assessments", []):
        item = _mapping(assessment)
        if item.get("slot_name") == slot_name:
            return item
    return None


def _matching_records(
    papers: Sequence[Mapping[str, Any]],
    subhypothesis_id: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for paper in papers:
        for raw_match in paper.get("sh_matches", []) if isinstance(paper.get("sh_matches"), list) else []:
            match = _mapping(raw_match)
            if match.get("sub_hypothesis_id") == subhypothesis_id:
                records.append((dict(paper), match))

    def sort_key(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[int, str]:
        semantic = _mapping(item[1].get("semantic_assessment"))
        try:
            score = int(semantic.get("semantic_relevance_score") or 0)
        except (TypeError, ValueError):
            score = 0
        return -score, paper_identity(item[0])

    return sorted(records, key=sort_key)


def _support_records_for_slot(
    records: Sequence[tuple[dict[str, Any], dict[str, Any]]],
    slot_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    supported: list[dict[str, Any]] = []
    background_only: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for paper, match in records:
        assessment = _assessment_for_slot(match, slot_name)
        if assessment is None:
            continue
        record = {
            "paper_id": paper_identity(paper),
            "evidence_role": assessment.get("expected_evidence_role", ""),
            "confirmed_evidence_types": list(assessment.get("confirmed_evidence_types") or []),
            "confirmed_evidence_roles": list(assessment.get("confirmed_evidence_roles") or []),
            "matched_concepts": list(assessment.get("matched_concepts") or []),
        }
        if assessment.get("covered"):
            supported.append(record)
        elif assessment.get("background_only"):
            background_only.append(record)
        elif assessment.get("coverage_status") in {
            "OUT_OF_SCOPE_OR_UNVERIFIED",
            "OUT_OF_SCOPE",
            "SCOPE_UNVERIFIED",
            "EXCLUDED",
        }:
            rejected.append(
                {
                    **record,
                    "coverage_status": assessment.get("coverage_status"),
                    "scope_assessment": _mapping(assessment.get("scope_assessment")),
                }
            )
    return supported, background_only, rejected


def _common_supporting_papers(slot_ledger: Mapping[str, Mapping[str, Any]], slots: Sequence[str]) -> list[str]:
    supporting_sets = [
        {str(record.get("paper_id") or "") for record in _mapping(slot_ledger.get(slot)).get("covered_by", [])}
        for slot in slots
    ]
    if not supporting_sets or any(not items for items in supporting_sets):
        return []
    return sorted(set.intersection(*supporting_sets))


def _admissibility(
    sh: Mapping[str, Any],
    slot_ledger: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    question_kind = str(sh.get("question_kind") or "")
    missing_slots = [slot for slot, item in slot_ledger.items() if item.get("missing")]
    background_only_slots = [slot for slot, item in slot_ledger.items() if item.get("background_only_by") and item.get("missing")]
    blockers = [f"missing_required_slot:{slot}" for slot in missing_slots]
    if background_only_slots:
        blockers.extend(f"background_only_slot:{slot}" for slot in background_only_slots)

    comparability_slots = _COMPARABILITY_SLOT_SETS.get(question_kind, ())
    comparable_papers = _common_supporting_papers(slot_ledger, comparability_slots)
    comparability_required = bool(comparability_slots)
    comparability_sufficient = not comparability_required or bool(comparable_papers)
    if comparability_required and not comparability_sufficient:
        blockers.append("comparability_insufficient")

    measurement_slots = _MEASUREMENT_SLOT_SETS.get(question_kind, ())
    measurement_papers = _common_supporting_papers(slot_ledger, measurement_slots)
    measurement_required = bool(measurement_slots)
    measurement_sufficient = not measurement_required or bool(measurement_papers)
    if measurement_required and not measurement_sufficient:
        blockers.append("measurement_insufficient")

    scope_rejections = [
        record
        for item in slot_ledger.values()
        for record in item.get("scope_rejections", [])
    ]
    scope_sufficient = bool(slot_ledger) and all(item.get("covered_by") for item in slot_ledger.values())
    if not scope_sufficient:
        blockers.append("scope_or_admission_insufficient")
    return {
        "status": "ADMISSIBLE_FOR_SYNTHESIS" if not blockers else "NOT_ADMISSIBLE",
        "admissible": not blockers,
        "blockers": _unique(blockers),
        "comparability": {
            "required": comparability_required,
            "sufficient": comparability_sufficient,
            "required_slots": list(comparability_slots),
            "supporting_paper_ids": comparable_papers,
        },
        "measurement": {
            "required": measurement_required,
            "sufficient": measurement_sufficient,
            "required_slots": list(measurement_slots),
            "supporting_paper_ids": measurement_papers,
        },
        "scope": {
            "sufficient": scope_sufficient,
            "rejections_or_unverified": scope_rejections,
        },
    }


def build_evidence_coverage_ledger(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    max_unique_papers_per_sh: int = 6,
    max_slots_per_paper: int = 2,
    project_id: str = "",
    project_context_fingerprint: str = "",
) -> dict[str, Any]:
    """Build a slot-level ledger and a separate bounded seed-allocation view."""

    paper_list = [dict(paper) for paper in papers or [] if isinstance(paper, Mapping)]
    sh_list = [
        _mapping(item)
        for item in subhypotheses or []
        if _mapping(item).get("retrieval_strategy") == "slot_driven_required_slot_recovery"
    ]
    per_sh_limit = max(1, int(max_unique_papers_per_sh))
    cap = max(1, int(max_slots_per_paper))
    all_assignments: list[dict[str, str]] = []
    paper_slots: dict[str, list[dict[str, str]]] = {}
    prevented: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []

    for sh in sh_list:
        subhypothesis_id = str(sh.get("sub_hypothesis_id") or "")
        records = _matching_records(paper_list, subhypothesis_id)
        bounded_records = records[:per_sh_limit]
        tasks = [
            _mapping(task)
            for task in sh.get("slot_recovery_tasks", [])
            if isinstance(task, Mapping)
        ]
        slot_ledger: dict[str, dict[str, Any]] = {}
        for task in tasks:
            slot_name = str(task.get("slot_name") or "")
            covered_by, background_only_by, scope_rejections = _support_records_for_slot(
                records,
                slot_name,
            )
            slot_ledger[slot_name] = {
                "task_id": str(task.get("task_id") or ""),
                "slot_name": slot_name,
                "expected_evidence_role": str(task.get("expected_evidence_role") or ""),
                "minimum_evidence": str(task.get("minimum_evidence") or ""),
                "admission_rule": str(task.get("admission_rule") or ""),
                "covered_by": covered_by,
                "background_only_by": background_only_by,
                "scope_rejections": scope_rejections,
                "missing": not covered_by,
                "missing_reason": (
                    "background_evidence_only"
                    if background_only_by and not covered_by
                    else "no_admissible_slot_evidence"
                    if not covered_by
                    else ""
                ),
            }

        for task in tasks:
            slot_name = str(task.get("slot_name") or "")
            for paper, match in bounded_records:
                assessment = _assessment_for_slot(match, slot_name)
                if assessment is None or not assessment.get("covered"):
                    continue
                paper_id = paper_identity(paper)
                allocations = paper_slots.setdefault(paper_id, [])
                if len(allocations) >= cap:
                    prevented.append(
                        {
                            "paper_id": paper_id,
                            "sub_hypothesis_id": subhypothesis_id,
                            "task_id": str(task.get("task_id") or ""),
                            "slot_name": slot_name,
                            "reason": "project_wide_max_slots_per_paper",
                        }
                    )
                    continue
                allocation = {
                    "paper_id": paper_id,
                    "sub_hypothesis_id": subhypothesis_id,
                    "task_id": str(task.get("task_id") or ""),
                    "slot_name": slot_name,
                }
                allocations.append({"sub_hypothesis_id": subhypothesis_id, "slot_name": slot_name})
                all_assignments.append(allocation)
                break

        admissibility = _admissibility(sh, slot_ledger)
        evidence_by_role: dict[str, list[dict[str, str]]] = {}
        for slot_name, item in slot_ledger.items():
            role = str(item.get("expected_evidence_role") or "")
            evidence_by_role.setdefault(role, [])
            evidence_by_role[role].extend(
                {"slot_name": slot_name, "paper_id": str(record.get("paper_id") or "")}
                for record in item.get("covered_by", [])
            )
        reports.append(
            {
                "sub_hypothesis_id": subhypothesis_id,
                "question": str(sh.get("question") or ""),
                "question_kind": str(sh.get("question_kind") or ""),
                "required_slots": [str(task.get("slot_name") or "") for task in tasks],
                "slot_ledger": slot_ledger,
                "covered_slots": [slot for slot, item in slot_ledger.items() if item.get("covered_by")],
                "background_only_slots": [slot for slot, item in slot_ledger.items() if item.get("background_only_by") and not item.get("covered_by")],
                "missing_slots": [slot for slot, item in slot_ledger.items() if item.get("missing")],
                "evidence_by_role": evidence_by_role,
                "conclusion_admissibility": admissibility,
                "candidate_paper_ids": [paper_identity(paper) for paper, _ in records],
                "evaluated_paper_ids": [paper_identity(paper) for paper, _ in bounded_records],
                "max_unique_papers": per_sh_limit,
                "truncated_candidate_count": max(0, len(records) - len(bounded_records)),
            }
        )
    return {
        "schema_version": EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION,
        # Low-level callers may leave these blank, but every project execution
        # emitted by WorkCollector supplies both. Consumers that join artifacts
        # across modules must reject a ledger without this identity.
        "project_id": str(project_id or "").strip(),
        "project_context_fingerprint": str(
            project_context_fingerprint or ""
        ).strip(),
        "subhypotheses": reports,
        "allocation": {
            "max_slots_per_paper": cap,
            "paper_slots": paper_slots,
            "slot_assignments": all_assignments,
            "prevented_slot_occupancy": prevented,
        },
        "complete": bool(reports) and all(
            _mapping(item.get("conclusion_admissibility")).get("admissible")
            for item in reports
        ),
    }


def _project_relevance_passes(paper: Mapping[str, Any], *, threshold: int) -> bool:
    record = _mapping(paper.get("project_relevance"))
    if not record or record.get("violated_exclusions"):
        return False
    try:
        return int(record.get("relevance_score") or 0) >= threshold
    except (TypeError, ValueError):
        return False


def _project_anchor_tokens(value: Any) -> list[str]:
    return [
        token
        for token in _normalized(value).split()
        if len(token) >= 4 and token not in _PROJECT_STOPWORDS
    ]


def ensure_deterministic_project_relevance(
    papers: Sequence[Mapping[str, Any]] | None,
    research_context: Mapping[str, Any] | None,
    *,
    threshold: int = 4,
) -> list[dict[str, Any]]:
    """Attach a conservative project relevance record when the LLM filter is off."""

    context = _mapping(research_context)
    retrieval_plan = _mapping(context.get("retrieval_plan"))
    topic = str(context.get("original_topic") or "").strip()
    include_anchors = _texts(retrieval_plan.get("include_anchors"), limit=12)
    core_entities = _texts(context.get("core_entities"), limit=12)
    exclusions = _texts(context.get("exclusion_terms"), limit=12)
    topic_tokens = _project_anchor_tokens(topic)
    output: list[dict[str, Any]] = []
    for original in papers or []:
        if not isinstance(original, Mapping):
            continue
        paper = dict(original)
        if _mapping(paper.get("project_relevance")):
            output.append(paper)
            continue
        text = _paper_text(paper)
        topic_matches = [token for token in topic_tokens if _contains(text, token)]
        matched_anchors = [f"topic:{token}" for token in topic_matches]
        matched_anchors.extend(
            f"include_anchor:{anchor}" for anchor in include_anchors if _contains(text, anchor)
        )
        matched_anchors.extend(
            f"core_entity:{entity}" for entity in core_entities if _contains(text, entity)
        )
        violated = [term for term in exclusions if _contains(text, term)]
        score = min(
            5,
            min(3, len(topic_matches))
            + min(1, sum(1 for anchor in include_anchors if _contains(text, anchor)))
            + min(1, sum(1 for entity in core_entities if _contains(text, entity))),
        )
        if violated:
            score = 0
        paper["project_relevance"] = {
            "assessment_source": "deterministic_project_context",
            "relevance_score": score,
            "project_fit": "deterministic_anchor_match" if score >= threshold else "insufficient_project_anchor_match",
            "matched_anchors": _unique(matched_anchors),
            "violated_exclusions": violated,
            "reason": "Project context anchors were matched deterministically.",
            "research_context_fingerprint": str(context.get("input_fingerprint") or ""),
        }
        output.append(paper)
    return output


def _semantic_seed_candidates(
    paper: Mapping[str, Any],
    *,
    threshold: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in paper.get("sh_semantic_assessments", []):
        assessment = _mapping(raw)
        if _semantic_assessment_is_seed_candidate(assessment, threshold=threshold):
            candidates.append(assessment)
    return candidates


def _semantic_seed_kind(assessments: Sequence[Mapping[str, Any]]) -> str:
    """Classify a graph root by its most evidence-bearing LLM contribution."""

    roles = {str(item.get("recommended_graph_role") or "") for item in assessments}
    if "evidence_seed" in roles:
        return "evidence_seed"
    if "exploration_seed" in roles:
        return "exploration_seed"
    return "context_seed"


def _seed_expansion_mode(seed_kind: str) -> str:
    return {
        "evidence_seed": "evidence_normal",
        "exploration_seed": "bounded_exploration",
        "context_seed": "context_only",
        "holdout_candidate": "holdout",
        "rejected": "do_not_expand",
    }.get(seed_kind, "holdout")


def _semantic_assessments(paper: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _mapping(raw)
        for raw in paper.get("sh_semantic_assessments", [])
        if _mapping(raw)
    ]


def _semantic_rejection_reason(paper: Mapping[str, Any]) -> str:
    if _has_explicit_project_exclusion(paper):
        return "explicit_project_exclusion"
    assessments = _semantic_assessments(paper)
    if any(item.get("explicit_exclusion_matches") for item in assessments):
        return "explicit_sh_exclusion"
    if assessments and all(item.get("overall_relation") == "irrelevant" for item in assessments):
        return "llm_assessed_irrelevant"
    return ""


def _semantic_priority(
    paper: Mapping[str, Any],
    seed_kind: str,
) -> tuple[int, int, str]:
    kind_rank = {"evidence_seed": 0, "exploration_seed": 1, "context_seed": 2}
    scores: list[int] = []
    for assessment in _semantic_assessments(paper):
        try:
            scores.append(int(assessment.get("semantic_relevance_score") or 0))
        except (TypeError, ValueError):
            continue
    return kind_rank.get(seed_kind, 3), -(max(scores) if scores else 0), paper_identity(paper)


def _fallback_seed_kind(paper: Mapping[str, Any]) -> str:
    roles = {
        role
        for match in paper.get("sh_matches", [])
        for role in _mapping(match).get("confirmed_evidence_roles", [])
    }
    return "context_seed" if roles and roles <= {"BACKGROUND_CONTEXT"} else "evidence_seed"


def _has_explicit_project_exclusion(paper: Mapping[str, Any]) -> bool:
    return bool(_mapping(paper.get("project_relevance")).get("violated_exclusions"))


def select_sh_seed_candidates(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    max_seed_papers: int,
    max_slots_per_paper: int = 2,
    require_project_relevance: bool = True,
    project_relevance_threshold: int = 4,
    semantic_relevance_threshold: int = 3,
    coverage_ledger: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose evidence, exploration, and context seeds after SH semantic annotation."""

    del require_project_relevance
    candidates = [paper for paper in papers or [] if isinstance(paper, dict)]
    ledger = _mapping(coverage_ledger) or build_evidence_coverage_ledger(
        candidates,
        subhypotheses,
        max_slots_per_paper=max_slots_per_paper,
    )
    indices: dict[str, list[int]] = {}
    for index, paper in enumerate(candidates):
        indices.setdefault(paper_identity(paper), []).append(index)
    all_semantic_by_index = {
        index: _semantic_assessments(paper)
        for index, paper in enumerate(candidates)
    }
    semantic_by_index = {
        index: _semantic_seed_candidates(
            paper,
            threshold=semantic_relevance_threshold,
        )
        for index, paper in enumerate(candidates)
    }
    eligible: set[int] = set()
    rejected: dict[int, str] = {}
    seed_kind_by_index: dict[int, str] = {}
    for index, paper in enumerate(candidates):
        rejection_reason = _semantic_rejection_reason(paper)
        if rejection_reason:
            rejected[index] = rejection_reason
            continue
        semantic_candidates = semantic_by_index[index]
        if semantic_candidates:
            # An SH-specific, grounded semantic assessment can promote a
            # partial/indirect/boundary contribution into a bounded graph root.
            # It never overrides an explicit project exclusion.
            eligible.add(index)
            seed_kind_by_index[index] = _semantic_seed_kind(semantic_candidates)
            continue

        # LLM assessment is optional for backward compatibility and outages. The
        # fallback deliberately uses only actual slot coverage, not the removed
        # aggregate relevance-score formula.
        has_legacy_coverage = any(
            _mapping(match).get("coverage_slots")
            for match in paper.get("sh_matches", [])
        )
        if (
            _project_relevance_passes(paper, threshold=project_relevance_threshold)
            and has_legacy_coverage
        ):
            eligible.add(index)
            seed_kind_by_index[index] = _fallback_seed_kind(paper)

    def eligible_priority(index: int) -> tuple[int, int, str]:
        return _semantic_priority(candidates[index], seed_kind_by_index[index])

    selected: list[int] = []
    selected_slots: dict[int, list[dict[str, str]]] = {}
    for raw_assignment in _mapping(ledger.get("allocation")).get("slot_assignments", []):
        assignment = _mapping(raw_assignment)
        paper_id = str(assignment.get("paper_id") or "")
        matching_indices = sorted(
            (item for item in indices.get(paper_id, []) if item in eligible),
            key=eligible_priority,
        )
        index = matching_indices[0] if matching_indices else None
        if index is None or (index not in selected and len(selected) >= max_seed_papers):
            continue
        if index not in selected:
            selected.append(index)
        selected_slots.setdefault(index, []).append(
            {
                "sub_hypothesis_id": str(assignment.get("sub_hypothesis_id") or ""),
                "slot": str(assignment.get("slot_name") or ""),
                "task_id": str(assignment.get("task_id") or ""),
            }
        )
    for index in sorted(eligible.difference(selected), key=eligible_priority):
        if len(selected) >= max_seed_papers:
            break
        selected.append(index)
        selected_slots.setdefault(index, [])

    evidence_seeds: list[dict[str, Any]] = []
    exploration_seeds: list[dict[str, Any]] = []
    context_seeds: list[dict[str, Any]] = []
    holdout_candidates: list[dict[str, Any]] = []
    rejected_papers: list[dict[str, Any]] = []
    selected_set = set(selected)
    for index, paper in enumerate(candidates):
        if index not in selected_set:
            if index in rejected:
                seed_kind = "rejected"
                reason = rejected[index]
                rejected_papers.append(paper)
            else:
                seed_kind = "holdout_candidate"
                reason = (
                    "not_selected_within_seed_budget"
                    if index in eligible
                    else "semantic_assessment_did_not_recommend_graph_expansion"
                    if all_semantic_by_index[index]
                    else "no_semantic_assessment_or_legacy_coverage"
                )
                holdout_candidates.append(paper)
            paper["seed_selection"] = {
                "eligible": index in eligible,
                "selected": False,
                "seed_kind": seed_kind,
                "graph_expansion_eligible": False,
                "graph_expansion_mode": _seed_expansion_mode(seed_kind),
                "decision_reason": reason,
                "selection_basis": (
                    "llm_sh_semantic_assessment"
                    if all_semantic_by_index[index]
                    else "legacy_covered_slot_fallback"
                ),
            }
            continue
        roles = {
            role
            for match in paper.get("sh_matches", [])
            for role in _mapping(match).get("confirmed_evidence_roles", [])
        }
        seed_kind = seed_kind_by_index[index]
        paper["seed_selection"] = {
            "eligible": True,
            "selected": True,
            "seed_kind": seed_kind,
            "selected_slots": selected_slots.get(index, []),
            "graph_expansion_eligible": seed_kind in {"evidence_seed", "exploration_seed"},
            "graph_expansion_mode": _seed_expansion_mode(seed_kind),
            "decision_reason": (
                "LLM classified this paper as a useful SH contribution for the selected seed role."
                if semantic_by_index[index]
                else "Legacy fallback retained a covered slot while LLM SH assessment was unavailable."
            ),
            "selection_basis": (
                "llm_sh_semantic_assessment"
                if semantic_by_index[index]
                else "legacy_covered_slot_fallback"
            ),
            "semantic_assessment_ids": [
                str(assessment.get("sub_hypothesis_id") or "")
                for assessment in semantic_by_index[index]
            ],
            "confirmed_evidence_roles": sorted(roles),
        }
        if seed_kind == "context_seed":
            context_seeds.append(paper)
        elif seed_kind == "exploration_seed":
            exploration_seeds.append(paper)
        else:
            evidence_seeds.append(paper)
    return {
        "selected_papers": [*evidence_seeds, *exploration_seeds, *context_seeds],
        "evidence_seed_papers": evidence_seeds,
        "exploration_seed_papers": exploration_seeds,
        "context_seed_papers": context_seeds,
        "holdout_candidates": holdout_candidates,
        "rejected_papers": rejected_papers,
        "allocation": _mapping(ledger.get("allocation")),
    }
