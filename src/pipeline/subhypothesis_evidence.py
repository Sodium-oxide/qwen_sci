"""Deterministic SH-to-paper evidence association, coverage, and seed selection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SUBHYPOTHESIS_EVIDENCE_SCHEMA_VERSION = "subhypothesis_evidence_v2"
_SLOT_BY_ROLE = {
    "direct_evidence": "direct_empirical",
    "mechanism": "mechanism",
    "boundary": "boundary_or_negative",
    "background": "review_or_background",
}
_SLOT_ORDER = (
    "direct_empirical",
    "mechanism",
    "boundary_or_negative",
    "review_or_background",
)
_ROLE_TO_EVIDENCE_TYPES = {
    "direct_evidence": {
        "primary_experiment",
        "observational_study",
        "benchmark",
        "deployment_evaluation",
    },
    "mechanism": {"mechanistic_study", "ablation"},
    "boundary": {"failure_analysis", "negative_result", "observational_study"},
    "background": {"review", "systematic_review", "meta_analysis"},
}
_EVIDENCE_TYPE_TO_BRANCH = {
    "primary_experiment": "direct_evidence",
    "observational_study": "direct_evidence",
    "benchmark": "direct_evidence",
    "deployment_evaluation": "direct_evidence",
    "mechanistic_study": "mechanism_method",
    "ablation": "mechanism_method",
    "failure_analysis": "boundary_negative",
    "negative_result": "boundary_negative",
    "review": "background_review",
    "systematic_review": "background_review",
    "meta_analysis": "background_review",
}
_EVIDENCE_TYPE_TERMS = {
    "primary_experiment": (
        "experiment",
        "experimental",
        "trial",
        "field study",
        "controlled study",
    ),
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
_SCOPE_TEXT_KEYS = ("contexts", "study_designs")
_SCOPE_VALUE_KEYS = ("languages", "publication_types", "providers", "source_types")
_PROJECT_STOPWORDS = frozenset(
    {
        "and",
        "for",
        "from",
        "into",
        "the",
        "with",
        "using",
        "use",
        "based",
        "study",
        "research",
    }
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen = set()
    for item in values:
        text = re.sub(r"\s+", " ", str(item or "").strip())[:180]
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
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def paper_identity(paper: Mapping[str, Any]) -> str:
    """Return the stable preference order used for SH coverage accounting."""

    raw = _mapping(paper)
    for key in ("openalex_id", "paperId", "paper_id", "doi"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    external_ids = _mapping(raw.get("externalIds"))
    for key in ("DOI", "doi", "ArXiv", "arXiv"):
        value = str(external_ids.get(key) or "").strip()
        if value:
            return value
    return re.sub(r"\W+", "", str(raw.get("title") or "").casefold()) or "unknown-paper"


def _paper_text(paper: Mapping[str, Any]) -> str:
    raw = _mapping(paper)
    return _normalized(
        " ".join(str(raw.get(key) or "") for key in ("title", "abstract", "venue"))
    )


def _matching_concepts(
    paper_text: str,
    retrieval_concepts: Mapping[str, Any],
) -> tuple[list[str], dict[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for group, raw_terms in retrieval_concepts.items():
        matched = [term for term in _texts(raw_terms, limit=8) if _contains(paper_text, term)]
        if matched:
            groups[str(group)] = matched
    concepts = _texts([term for values in groups.values() for term in values])
    return concepts, groups


def _provenance_for_sh(paper: Mapping[str, Any], subhypothesis_id: str) -> list[dict[str, Any]]:
    records = paper.get("retrieval_provenance")
    result: list[dict[str, Any]] = []
    for record in records if isinstance(records, list) else []:
        item = _mapping(record)
        if item and str(item.get("sub_hypothesis_id") or "") == subhypothesis_id:
            result.append(item)
    return result


def _retrieved_evidence_roles(provenance: Sequence[Mapping[str, Any]]) -> list[str]:
    return _unique(
        [
            str(record.get("evidence_role") or "").strip()
            for record in provenance
            if str(record.get("evidence_role") or "").strip() in _SLOT_BY_ROLE
        ]
    )


def _confirmed_evidence_types(paper_text: str) -> list[str]:
    return [
        evidence_type
        for evidence_type, terms in _EVIDENCE_TYPE_TERMS.items()
        if any(_contains(paper_text, term) for term in terms)
    ]


def _confirmed_evidence_roles(
    evidence_types: Sequence[str],
    concept_groups: Mapping[str, list[str]],
) -> list[str]:
    evidence_type_set = set(evidence_types)
    has_object = bool(concept_groups.get("object"))
    has_direct_context = sum(
        bool(concept_groups.get(group))
        for group in ("input_or_intervention", "outcomes", "conditions")
    ) >= 2
    has_mechanism_context = bool(
        concept_groups.get("mechanism") or concept_groups.get("input_or_intervention")
    )
    has_boundary_context = bool(
        concept_groups.get("boundary") or concept_groups.get("conditions")
    )
    has_background_context = bool(concept_groups.get("background") or has_object)
    roles: list[str] = []
    if has_object and has_direct_context and evidence_type_set & _ROLE_TO_EVIDENCE_TYPES["direct_evidence"]:
        roles.append("direct_evidence")
    if has_object and has_mechanism_context and evidence_type_set & _ROLE_TO_EVIDENCE_TYPES["mechanism"]:
        roles.append("mechanism")
    if has_object and has_boundary_context and evidence_type_set & _ROLE_TO_EVIDENCE_TYPES["boundary"]:
        roles.append("boundary")
    if has_background_context and evidence_type_set & _ROLE_TO_EVIDENCE_TYPES["background"]:
        roles.append("background")
    return roles


def _scope_values(scope: Mapping[str, Any], key: str) -> list[str]:
    return _texts(scope.get(key), limit=8)


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

    allowed_ranges = _year_ranges(_scope_values(allowed, "date_range"))
    excluded_ranges = _year_ranges(_scope_values(excluded, "date_range"))
    if _scope_values(allowed, "date_range"):
        year = _paper_year(paper)
        if not allowed_ranges or year is None:
            unverified.append("allowed_date_range")
        elif any(start <= year <= end for start, end in allowed_ranges):
            allowed_matches.append(f"date_range:{year}")
        else:
            violations.append(f"allowed_date_range:{year}")
    if _scope_values(excluded, "date_range"):
        year = _paper_year(paper)
        if not excluded_ranges or year is None:
            unverified.append("excluded_date_range")
        elif any(start <= year <= end for start, end in excluded_ranges):
            violations.append(f"excluded_date_range:{year}")

    for key in _SCOPE_VALUE_KEYS:
        allowed_values = _scope_values(allowed, key)
        excluded_values = _scope_values(excluded, key)
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
        allowed_values = _scope_values(allowed, key)
        excluded_values = _scope_values(excluded, key)
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
    if _scope_values(allowed, "notes"):
        unverified.append("allowed_notes")
    excluded_notes = _scope_values(excluded, "notes")
    note_matches = [note for note in excluded_notes if _contains(paper_text, note)]
    violations.extend(f"excluded_notes:{note}" for note in note_matches)
    if excluded_notes and not note_matches:
        unverified.append("excluded_notes")
    return {
        "allowed_matches": _unique(allowed_matches),
        "violations": _unique(violations),
        "unverified": _unique(unverified),
    }


def associate_papers_with_subhypotheses(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    project_fingerprint: str = "",
    relevance_threshold: int = 3,
    max_slots_per_paper: int = 2,
) -> list[dict[str, Any]]:
    """Attach SH evidence candidates without treating retrieval branch as proof.

    ``retrieval_provenance`` tells us where a paper was found. Only explicit
    title/abstract evidence confirms a role, and only scope-verified SH branch
    candidates may later occupy a coverage slot. Actual slot allocation is
    deferred to :func:`build_subhypothesis_coverage_report`, where the
    per-paper cap applies across the full project rather than per SH.
    """

    del max_slots_per_paper, relevance_threshold
    normalized_subhypotheses = [
        _mapping(item)
        for item in subhypotheses or []
        if isinstance(item, Mapping) and _mapping(item).get("sub_hypothesis_id")
    ]
    output: list[dict[str, Any]] = []
    for original_paper in papers or []:
        if not isinstance(original_paper, Mapping):
            continue
        paper = dict(original_paper)
        text = _paper_text(paper)
        matches: list[dict[str, Any]] = []
        aggregate_roles: list[str] = []
        aggregate_slots: list[dict[str, str]] = []
        aggregate_provenance: list[dict[str, Any]] = []
        for subhypothesis in normalized_subhypotheses:
            subhypothesis_id = str(subhypothesis["sub_hypothesis_id"])
            concepts, concept_groups = _matching_concepts(
                text,
                _mapping(subhypothesis.get("retrieval_concepts")),
            )
            exclusions = _texts(subhypothesis.get("exclusion_terms"))
            exclusion_violations = [term for term in exclusions if _contains(text, term)]
            provenance = _provenance_for_sh(paper, subhypothesis_id)
            retrieved_roles = _retrieved_evidence_roles(provenance)
            confirmed_types = _confirmed_evidence_types(text)
            confirmed_roles = _confirmed_evidence_roles(confirmed_types, concept_groups)
            scope = _scope_assessment(
                paper,
                text,
                _mapping(subhypothesis.get("allowed_evidence_scope")),
                _mapping(subhypothesis.get("excluded_evidence_scope")),
            )
            potential_slots = [_SLOT_BY_ROLE[role] for role in confirmed_roles]
            scope_ok = not scope["violations"] and not scope["unverified"]
            eligible = bool(
                not exclusion_violations
                and scope_ok
                and provenance
                and potential_slots
            )
            match = {
                "sub_hypothesis_id": subhypothesis_id,
                "matched_concepts": concepts,
                "matched_concept_groups": concept_groups,
                "violated_exclusions": exclusion_violations,
                "scope_assessment": scope,
                "retrieved_evidence_roles": retrieved_roles,
                "confirmed_evidence_types": confirmed_types,
                "confirmed_evidence_roles": confirmed_roles,
                "evidence_roles": confirmed_roles,
                "coverage_slots": potential_slots if eligible else [],
                "potential_coverage_slots": potential_slots,
                "allocated_coverage_slots": [],
                "branch_provenance": provenance,
                "research_context_fingerprint": project_fingerprint,
                "eligible": eligible,
                "ineligible_reason": (
                    "scope_rejected"
                    if scope["violations"] or scope["unverified"]
                    else "excluded"
                    if exclusion_violations
                    else "missing_sh_branch_provenance"
                    if not provenance
                    else "insufficient_confirmed_evidence"
                    if not potential_slots
                    else ""
                ),
            }
            matches.append(match)
            if eligible:
                for role in confirmed_roles:
                    if role not in aggregate_roles:
                        aggregate_roles.append(role)
                for slot in potential_slots:
                    pair = {"sub_hypothesis_id": subhypothesis_id, "slot": slot}
                    if pair not in aggregate_slots:
                        aggregate_slots.append(pair)
                for record in provenance:
                    if record not in aggregate_provenance:
                        aggregate_provenance.append(record)
        paper["sh_matches"] = matches
        paper["evidence_roles"] = aggregate_roles
        paper["coverage_slots"] = aggregate_slots
        paper["branch_provenance"] = aggregate_provenance
        output.append(paper)
    return output


def _match_candidates(
    paper_list: Sequence[Mapping[str, Any]],
    subhypothesis_id: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for paper in paper_list:
        for match in paper.get("sh_matches") if isinstance(paper.get("sh_matches"), list) else []:
            item = _mapping(match)
            if item.get("sub_hypothesis_id") == subhypothesis_id:
                candidates.append((dict(paper), item))
    candidates.sort(
        key=lambda item: (
            -len(item[1].get("coverage_slots") or []),
            paper_identity(item[0]),
        )
    )
    return candidates


def _paper_diversity_values(paper: Mapping[str, Any]) -> tuple[str, str, list[str], str]:
    provider = str(paper.get("api_platform") or paper.get("provider") or "").strip()
    venue = str(paper.get("venue") or "").strip()
    raw_authors = paper.get("authors")
    authors = [
        str(_mapping(author).get("name") or author or "").strip()
        for author in (raw_authors if isinstance(raw_authors, list) else [])
    ]
    authors = [author for author in authors if author]
    source_type = _paper_scope_value(paper, "source_types")
    return provider, venue, authors, source_type


def build_subhypothesis_coverage_report(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    max_unique_papers_per_sh: int = 6,
    max_slots_per_paper: int = 2,
    min_unique_venues: int = 2,
) -> dict[str, Any]:
    """Allocate SH coverage slots with one project-wide paper-slot ledger."""

    paper_list = [dict(paper) for paper in papers or [] if isinstance(paper, Mapping)]
    sh_list = [
        _mapping(item)
        for item in subhypotheses or []
        if _mapping(item).get("sub_hypothesis_id")
    ]
    cap = max(1, int(max_slots_per_paper))
    per_sh_limit = max(1, int(max_unique_papers_per_sh))
    candidates_by_sh = {
        str(sh["sub_hypothesis_id"]): _match_candidates(paper_list, str(sh["sub_hypothesis_id"]))
        for sh in sh_list
    }
    bounded_by_sh = {
        subhypothesis_id: candidates[:per_sh_limit]
        for subhypothesis_id, candidates in candidates_by_sh.items()
    }

    paper_slots: dict[str, list[dict[str, str]]] = {}
    assignments: list[dict[str, str]] = []
    prevented: list[dict[str, Any]] = []
    assignments_by_sh: dict[str, list[dict[str, str]]] = {
        str(sh["sub_hypothesis_id"]): [] for sh in sh_list
    }
    for sh in sh_list:
        subhypothesis_id = str(sh["sub_hypothesis_id"])
        bounded = bounded_by_sh[subhypothesis_id]
        for slot in _SLOT_ORDER:
            for paper, match in bounded:
                if not match.get("eligible") or slot not in match.get("potential_coverage_slots", []):
                    continue
                paper_id = paper_identity(paper)
                existing = paper_slots.setdefault(paper_id, [])
                if len(existing) >= cap:
                    prevented.append(
                        {
                            "paper_id": paper_id,
                            "sub_hypothesis_id": subhypothesis_id,
                            "slot": slot,
                            "assigned_slots": list(existing),
                            "reason": "project_wide_max_slots_per_paper",
                        }
                    )
                    continue
                assignment = {
                    "paper_id": paper_id,
                    "sub_hypothesis_id": subhypothesis_id,
                    "slot": slot,
                }
                existing.append({"sub_hypothesis_id": subhypothesis_id, "slot": slot})
                assignments.append(assignment)
                assignments_by_sh[subhypothesis_id].append(assignment)
                break

    reports: list[dict[str, Any]] = []
    for sh in sh_list:
        subhypothesis_id = str(sh["sub_hypothesis_id"])
        candidates = candidates_by_sh[subhypothesis_id]
        bounded = bounded_by_sh[subhypothesis_id]
        slot_assignments = assignments_by_sh[subhypothesis_id]
        slots = {slot: [] for slot in _SLOT_ORDER}
        assigned_paper_ids = {record["paper_id"] for record in slot_assignments}
        selected_papers = {
            paper_identity(paper): paper
            for paper, _match in bounded
            if paper_identity(paper) in assigned_paper_ids
        }
        confirmed_types: set[str] = set()
        scope_rejections: list[dict[str, Any]] = []
        for paper, match in bounded:
            paper_id = paper_identity(paper)
            scope = _mapping(match.get("scope_assessment"))
            if scope.get("violations") or scope.get("unverified"):
                scope_rejections.append(
                    {
                        "paper_id": paper_id,
                        "violations": list(scope.get("violations") or []),
                        "unverified": list(scope.get("unverified") or []),
                    }
                )
            for assignment in slot_assignments:
                if assignment["paper_id"] == paper_id:
                    slots[assignment["slot"]].append(paper_id)
                    confirmed_types.update(match.get("confirmed_evidence_types") or [])
        missing_slots = [slot for slot, paper_ids in slots.items() if not paper_ids]
        required_types = _unique(_texts(sh.get("required_evidence_types"), limit=12))
        missing_required_types = [
            evidence_type for evidence_type in required_types if evidence_type not in confirmed_types
        ]
        providers, venues, authors, source_types = set(), set(), set(), set()
        for paper in selected_papers.values():
            provider, venue, author_names, source_type = _paper_diversity_values(paper)
            if provider:
                providers.add(provider)
            if venue:
                venues.add(venue)
            authors.update(author_names)
            if source_type:
                source_types.add(source_type)
        diversity_issues: list[str] = []
        if len(venues) < min_unique_venues:
            diversity_issues.append("venue_concentration")
        if authors and len(authors) < min_unique_venues:
            diversity_issues.append("author_concentration")
        slot_complete = not missing_slots
        required_evidence_complete = not missing_required_types
        scope_complete = True
        diversity_complete = not diversity_issues
        reports.append(
            {
                "sub_hypothesis_id": subhypothesis_id,
                "question": str(sh.get("question") or ""),
                "required_slots": list(_SLOT_ORDER),
                "required_evidence_types": required_types,
                "confirmed_evidence_types": sorted(confirmed_types),
                "missing_required_evidence_types": missing_required_types,
                "slots": slots,
                "slot_assignments": slot_assignments,
                "missing_slots": missing_slots,
                "slot_complete": slot_complete,
                "required_evidence_complete": required_evidence_complete,
                "scope_complete": scope_complete,
                "diversity_complete": diversity_complete,
                "covered": slot_complete,
                "complete": bool(
                    slot_complete
                    and required_evidence_complete
                    and scope_complete
                    and diversity_complete
                ),
                "candidate_paper_ids": [paper_identity(paper) for paper, _ in candidates],
                "evaluated_paper_ids": [paper_identity(paper) for paper, _ in bounded],
                "allocated_paper_ids": sorted(assigned_paper_ids),
                "max_unique_papers": per_sh_limit,
                "truncated_candidate_count": max(0, len(candidates) - len(bounded)),
                "scope_rejections": scope_rejections,
                "source_diversity": {
                    "providers": sorted(providers),
                    "venues": sorted(venues),
                    "authors": sorted(authors),
                    "source_types": sorted(source_types),
                    "issues": diversity_issues,
                },
                "duplicate_slot_occupancy": [],
                "prevented_duplicate_slot_occupancy": [
                    item for item in prevented if item["sub_hypothesis_id"] == subhypothesis_id
                ],
            }
        )
    return {
        "schema_version": SUBHYPOTHESIS_EVIDENCE_SCHEMA_VERSION,
        "subhypotheses": reports,
        "allocation": {
            "max_slots_per_paper": cap,
            "paper_slots": paper_slots,
            "slot_assignments": assignments,
            "prevented_duplicate_slot_occupancy": prevented,
        },
        "complete": bool(reports) and all(report["complete"] for report in reports),
    }


def missing_branch_ids(coverage_report: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """Map missing slots and diversity gaps to one bounded supplement round."""

    slot_to_branch = {
        "direct_empirical": "direct_evidence",
        "mechanism": "mechanism_method",
        "boundary_or_negative": "boundary_negative",
        "review_or_background": "background_review",
    }
    all_branches = list(slot_to_branch.values())
    result: dict[str, list[str]] = {}
    for report in _mapping(coverage_report).get("subhypotheses", []):
        item = _mapping(report)
        subhypothesis_id = str(item.get("sub_hypothesis_id") or "")
        branch_ids = [
            slot_to_branch[slot]
            for slot in item.get("missing_slots", [])
            if slot in slot_to_branch
        ]
        for evidence_type in item.get("missing_required_evidence_types", []):
            branch_id = _EVIDENCE_TYPE_TO_BRANCH.get(str(evidence_type))
            if branch_id:
                branch_ids.append(branch_id)
        if not item.get("diversity_complete", True):
            branch_ids.extend(all_branches)
        if subhypothesis_id and branch_ids:
            result[subhypothesis_id] = _unique(branch_ids)
    return result


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
    operationalization = _mapping(context.get("academic_operationalization"))
    topic = str(context.get("original_topic") or "").strip()
    include_anchors = _texts(retrieval_plan.get("include_anchors"), limit=12)
    core_entities = _texts(context.get("core_entities"), limit=12)
    objective = str(operationalization.get("normalized_objective") or "").strip()
    exclusions = _texts(context.get("exclusion_terms"), limit=12)
    topic_tokens = _project_anchor_tokens(topic)
    output: list[dict[str, Any]] = []
    for original_paper in papers or []:
        if not isinstance(original_paper, Mapping):
            continue
        paper = dict(original_paper)
        if _mapping(paper.get("project_relevance")):
            output.append(paper)
            continue
        text = _paper_text(paper)
        matched_anchors: list[str] = []
        topic_matches = [token for token in topic_tokens if _contains(text, token)]
        if topic_matches:
            matched_anchors.extend(f"topic:{token}" for token in topic_matches)
        for anchor in include_anchors:
            if _contains(text, anchor):
                matched_anchors.append(f"include_anchor:{anchor}")
        for entity in core_entities:
            if _contains(text, entity):
                matched_anchors.append(f"core_entity:{entity}")
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


def _match_is_seed_eligible(match: Mapping[str, Any]) -> bool:
    scope = _mapping(match.get("scope_assessment"))
    return bool(
        match.get("eligible")
        and not match.get("violated_exclusions")
        and not scope.get("violations")
        and not scope.get("unverified")
        and match.get("confirmed_evidence_roles")
        and match.get("potential_coverage_slots")
    )


def select_sh_seed_candidates(
    papers: Sequence[Mapping[str, Any]] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    max_seed_papers: int,
    max_slots_per_paper: int = 2,
    require_project_relevance: bool = True,
    project_relevance_threshold: int = 4,
    coverage_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select graph and context seeds from one shared SH allocation ledger."""

    del require_project_relevance
    candidates = [paper for paper in papers or [] if isinstance(paper, dict)]
    report = _mapping(coverage_report)
    if not report:
        report = build_subhypothesis_coverage_report(
            candidates,
            subhypotheses,
            max_slots_per_paper=max_slots_per_paper,
        )
    paper_indices: dict[str, list[int]] = {}
    eligible_indices: set[int] = set()
    for index, paper in enumerate(candidates):
        paper_indices.setdefault(paper_identity(paper), []).append(index)
        if not _project_relevance_passes(paper, threshold=project_relevance_threshold):
            continue
        if any(
            _match_is_seed_eligible(_mapping(match))
            for match in paper.get("sh_matches") if isinstance(paper.get("sh_matches"), list)
        ):
            eligible_indices.add(index)

    selected_indices: list[int] = []
    selected_slots: dict[int, list[dict[str, str]]] = {}
    for assignment in _mapping(report.get("allocation")).get("slot_assignments", []):
        record = _mapping(assignment)
        paper_id = str(record.get("paper_id") or "")
        index = next((candidate for candidate in paper_indices.get(paper_id, []) if candidate in eligible_indices), None)
        if index is None:
            continue
        if index not in selected_indices and len(selected_indices) >= max_seed_papers:
            continue
        if index not in selected_indices:
            selected_indices.append(index)
        selected_slots.setdefault(index, []).append(
            {
                "sub_hypothesis_id": str(record.get("sub_hypothesis_id") or ""),
                "slot": str(record.get("slot") or ""),
            }
        )

    def seed_rank(index: int) -> tuple[int, str]:
        coverage_counts = [
            len(_mapping(match).get("coverage_slots") or [])
            for match in candidates[index].get("sh_matches", [])
            if isinstance(match, Mapping)
        ]
        return (-max(coverage_counts, default=0), paper_identity(candidates[index]))

    for index in sorted(eligible_indices.difference(selected_indices), key=seed_rank):
        if len(selected_indices) >= max_seed_papers:
            break
        selected_indices.append(index)
        selected_slots.setdefault(index, [])

    evidence_seeds: list[dict[str, Any]] = []
    context_seeds: list[dict[str, Any]] = []
    selected_set = set(selected_indices)
    for index, paper in enumerate(candidates):
        if index not in selected_set:
            paper["seed_selection"] = {
                "eligible": index in eligible_indices,
                "selected": False,
                "reason": "not_selected_within_seed_budget" if index in eligible_indices else "failed_project_or_sh_gate",
            }
            continue
        confirmed_roles = set()
        for match in paper.get("sh_matches") if isinstance(paper.get("sh_matches"), list) else []:
            item = _mapping(match)
            if _match_is_seed_eligible(item):
                confirmed_roles.update(item.get("confirmed_evidence_roles") or [])
        seed_kind = "context_seed" if confirmed_roles and confirmed_roles <= {"background"} else "evidence_seed"
        paper["seed_selection"] = {
            "eligible": True,
            "selected": True,
            "seed_kind": seed_kind,
            "selected_slots": selected_slots.get(index, []),
            "project_relevance_required": True,
            "confirmed_evidence_roles": sorted(confirmed_roles),
        }
        if seed_kind == "context_seed":
            context_seeds.append(paper)
        else:
            evidence_seeds.append(paper)
    return {
        "schema_version": SUBHYPOTHESIS_EVIDENCE_SCHEMA_VERSION,
        "evidence_seed_papers": evidence_seeds,
        "context_seed_papers": context_seeds,
        "selected_papers": [candidates[index] for index in selected_indices],
        "eligible_paper_count": len(eligible_indices),
        "max_seed_papers": max_seed_papers,
        "coverage_allocation": _mapping(report.get("allocation")),
    }
