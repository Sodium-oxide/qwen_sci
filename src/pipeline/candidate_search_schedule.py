"""Contract-derived screening and diversity-aware bounded comparison."""

from .scientific_candidates import comparison_key, evidence_id, is_decision_candidate, normalize_evidence_assessment


def screening_dimensions(dimensions, limit=1):
    required = [dimension for dimension in dimensions if dimension.get("required", True)]
    ordered = sorted(enumerate(required), key=lambda item: (
        not bool(item[1].get("screening_priority")),
        item[1].get("evidence_role") not in {"DIRECT_OBSERVATION", "DIRECT_COMPARATIVE_EVIDENCE"}, item[0]))
    return [dimension for _index, dimension in ordered[:max(1, limit)]]


def accepted_dimension_papers(papers, candidate, sh_id, dimension):
    accepted = {}
    for paper in papers:
        for assessment in paper.get("candidate_evidence_assessments", []):
            if (assessment.get("candidate_id"), assessment.get("sub_hypothesis_id"), assessment.get("dimension")) != (
                candidate["candidate_id"], sh_id, dimension["slot_name"]):
                continue
            normalized = normalize_evidence_assessment(assessment, paper=paper, candidate=candidate, sh_id=sh_id, dimension=dimension)
            if normalized["eligible"] and assessment.get("assessment_status") == "assessed":
                accepted[evidence_id(paper)] = normalized
    return accepted


def dimension_satisfied(papers, candidate, sh_id, dimension):
    return len(accepted_dimension_papers(papers, candidate, sh_id, dimension)) >= dimension.get("minimum_independent_works", 1)


def promotion_order(registry, papers, sh_id, dimensions, limit):
    candidates = [candidate for candidate in registry if is_decision_candidate(candidate, sh_id)
                  and candidate.get("screening_status_by_subhypothesis", {}).get(sh_id) == "completed"]
    scored = []
    for candidate in candidates:
        evidence = [accepted_dimension_papers(papers, candidate, sh_id, dimension) for dimension in dimensions]
        covered = sum(bool(works) for works in evidence)
        nonnegative = sum(any(value["stance"] != "negative" for value in works.values()) for works in evidence)
        direct = sum(bool(works) and dimension.get("evidence_role") in {"DIRECT_OBSERVATION", "DIRECT_COMPARATIVE_EVIDENCE"}
                     for works, dimension in zip(evidence, dimensions))
        scored.append((candidate, (-nonnegative, -direct, -covered, candidate["candidate_id"])))
    remaining = [candidate for candidate, _score in sorted(scored, key=lambda item: item[1])]
    selected = []
    classes = set()
    while remaining and len(selected) < limit:
        if len(selected) == 1:
            choice = next((candidate for candidate in remaining if comparison_key(candidate) == comparison_key(selected[0])), remaining[0])
        else:
            choice = next((candidate for candidate in remaining if comparison_key(candidate) not in classes), remaining[0])
        selected.append(choice)
        remaining.remove(choice)
        classes.add(comparison_key(choice))
    return selected


def interleave(groups):
    groups = [iter(group) for group in groups]
    while groups:
        active = []
        for group in groups:
            value = next(group, None)
            if value is not None:
                yield value
                active.append(group)
        groups = active
