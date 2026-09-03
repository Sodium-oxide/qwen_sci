"""Build mature-idea portfolios from heterogeneous sources and scoped evidence."""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from src.agents.idea_agent.utils.workflow.idea_contract import (
    normalize_mature_ideas,
)
from src.agents.idea_agent.utils.workflow.idea_diversity import (
    filter_independent_mature_ideas,
)
from src.agents.idea_agent.utils.workflow.multimodal_data_anchoring import (
    annotate_data_anchored_mature_idea,
    scoped_multimodal_evidence_for_idea,
)


MATURE_IDEA_SOURCES = (
    "user_input",
    "survey_gap",
    "prior_candidate",
    "experiment_feedback",
    "problem_reframing",
    "adversarial_generation",
    "cross_domain_transfer",
)

_SOURCE_ALIASES = {
    "survey": "survey_gap",
    "survey_gap": "survey_gap",
    "history": "prior_candidate",
    "prior": "prior_candidate",
    "prior_candidate": "prior_candidate",
    "experiment": "experiment_feedback",
    "experiment_feedback": "experiment_feedback",
    "generated": "problem_reframing",
    "problem_reframing": "problem_reframing",
    "adversarial": "adversarial_generation",
    "adversarial_generation": "adversarial_generation",
    "cross_domain": "cross_domain_transfer",
    "cross_domain_transfer": "cross_domain_transfer",
    "user": "user_input",
    "user_input": "user_input",
}

_ACTIVE_GAP_ROUTES = {
    "core_hypothesis",
    "provisional_hypothesis",
    "exploratory_frontier",
    "future_work_seed",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _unique(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in _list(values):
        item = _text(value)
        if not item or item.casefold() in seen:
            continue
        seen.add(item.casefold())
        result.append(item)
    return result


def _canonical_source(value: Any, default: str = "user_input") -> str:
    source = _text(value).casefold()
    return _SOURCE_ALIASES.get(source, _text(default) or "user_input")


def _source_record(raw: Any, source: str, *, index: int = 0, lineage: Any = None) -> Dict[str, Any]:
    if isinstance(raw, Mapping):
        record = dict(raw)
    else:
        record = {"title": _text(raw), "hypothesis": _text(raw)}
    source = _canonical_source(source)
    lineage = lineage if lineage is not None else source
    record["idea_source"] = source
    record["lineage"] = lineage
    if not record.get("source_lineage"):
        record["source_lineage"] = [{"idea_source": source, "lineage": deepcopy(lineage)}]
    if not _text(record.get("maturity_status")):
        record["maturity_status"] = "provisional" if source in {"survey_gap", "experiment_feedback"} else "mature"
    if not _text(record.get("idea_id")):
        record["idea_id"] = f"{source}-{index + 1:02d}"
    return record


def _gap_rows(survey_handoff: Any, gap_triage: Any = None) -> List[Dict[str, Any]]:
    handoff = survey_handoff if isinstance(survey_handoff, Mapping) else {}
    triage_candidate = gap_triage if isinstance(gap_triage, Mapping) else handoff.get("gap_triage")
    triage = dict(triage_candidate) if isinstance(triage_candidate, Mapping) else {}
    triage_by_id = {
        _text(row.get("gap_id")): row
        for row in _list(triage.get("gaps"))
        if isinstance(row, Mapping) and _text(row.get("gap_id"))
    }
    rows: List[Dict[str, Any]] = []
    for row in _list(handoff.get("gaps")):
        if not isinstance(row, Mapping):
            continue
        gap_id = _text(row.get("gap_id"))
        triage_row = triage_by_id.get(gap_id, {})
        route = _text(triage_row.get("eligibility_route") or row.get("eligibility_route"))
        if route and route not in _ACTIVE_GAP_ROUTES:
            continue
        rows.append({**dict(row), **dict(triage_row)})
    if rows:
        return rows
    return [dict(row) for row in triage_by_id.values()]


def _survey_gap_ideas(survey_handoff: Any, gap_triage: Any = None, *, limit: int = 4) -> List[Dict[str, Any]]:
    ideas: List[Dict[str, Any]] = []
    gap_rows = _gap_rows(survey_handoff, gap_triage)[:limit]
    for index, gap in enumerate(gap_rows):
        gap_id = _text(gap.get("gap_id"))
        statement = _text(gap.get("statement") or gap.get("gap") or gap.get("description"))
        target_object = gap.get("target_object") or gap.get("scientific_object") or gap.get("object")
        mechanism = _text(gap.get("mechanism") or gap.get("missing_mechanism") or gap.get("target_slot"))
        evidence = gap.get("evidence_basis") or gap.get("source_anchors") or gap.get("evidence_roles") or []
        ideas.append(
            _source_record(
                {
                    "idea_id": f"survey-gap-{gap_id or index + 1}",
                    "title": _text(gap.get("title")) or f"Gap route: {gap_id or index + 1}",
                    "abstract": statement,
                    "hypothesis": statement or f"The unresolved relation associated with {gap_id} is testable.",
                    "scientific_object": target_object or {},
                    "mechanism": mechanism,
                    "mechanism_or_relation": mechanism,
                    "target_gap_ids": [gap_id] if gap_id else [],
                    "gap_alignment": [{"gap_id": gap_id, "alignment": "survey_gap"}] if gap_id else [],
                    "evidence_basis": evidence,
                    "refinement_scope": _text(gap.get("target_slot") or gap.get("refinement_scope")),
                    "falsifier": _text(gap.get("falsifier") or gap.get("discriminating_observation"))
                    or "A result showing the stated gap is resolved without this hypothesis.",
                },
                "survey_gap",
                index=index,
                lineage={"source": "survey", "gap_id": gap_id},
            )
        )
    if len(gap_rows) >= 2:
        for index, pair in enumerate(combinations(gap_rows[:3], 2)):
            gap_ids = [_text(item.get("gap_id")) for item in pair if _text(item.get("gap_id"))]
            statements = [
                _text(item.get("statement") or item.get("gap") or item.get("description"))
                for item in pair
            ]
            ideas.append(
                _source_record(
                    {
                        "idea_id": "survey-gap-combination-" + "-".join(gap_ids),
                        "title": "Combined gap route: " + " + ".join(gap_ids),
                        "abstract": " | ".join(item for item in statements if item),
                        "hypothesis": "The joint constraints represented by " + ", ".join(gap_ids) + " admit a shared mechanism.",
                        "scientific_object": [
                            _text(item.get("target_object") or item.get("scientific_object"))
                            for item in pair
                        ],
                        "mechanism": "Joint mechanism linking the selected gap constraints.",
                        "target_gap_ids": gap_ids,
                        "gap_alignment": [
                            {"gap_id": gap_id, "alignment": "combined_survey_gaps"}
                            for gap_id in gap_ids
                        ],
                        "evidence_basis": [
                            item.get("evidence_basis") or item.get("source_anchors") or []
                            for item in pair
                        ],
                        "falsifier": "Evidence that the selected gaps require mutually incompatible mechanisms.",
                    },
                    "survey_gap",
                    index=limit + index,
                    lineage={"source": "survey", "gap_ids": gap_ids, "combination": True},
                )
            )
    return ideas


def _survey_subhypothesis_ideas(survey_handoff: Any, *, limit: int = 6) -> List[Dict[str, Any]]:
    """Promote independent Survey sub-hypotheses into source records."""

    handoff = survey_handoff if isinstance(survey_handoff, Mapping) else {}
    raw_rows: List[Any] = []
    for key in ("subhypotheses", "sub_hypotheses", "hypothesis_seeds", "subhypothesis_candidates"):
        value = handoff.get(key)
        if isinstance(value, Mapping):
            value = value.get("items") or value.get("records") or value.get("seeds") or []
        raw_rows.extend(_list(value))
    ideas: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_rows[:limit]):
        if not isinstance(raw, Mapping):
            continue
        gap_ids = _unique(raw.get("target_gap_ids") or raw.get("gap_ids") or raw.get("gap_id"))
        hypothesis = _text(raw.get("hypothesis") or raw.get("central_hypothesis") or raw.get("statement"))
        if not hypothesis and not _text(raw.get("title")):
            continue
        ideas.append(
            _source_record(
                {
                    **dict(raw),
                    "idea_id": _text(raw.get("idea_id")) or f"survey-subhypothesis-{index + 1:02d}",
                    "title": _text(raw.get("title")) or f"Survey sub-hypothesis {index + 1}",
                    "hypothesis": hypothesis,
                    "target_gap_ids": gap_ids,
                    "evidence_basis": raw.get("evidence_basis") or raw.get("source_anchors") or [],
                },
                "survey_gap",
                index=index,
                lineage={"source": "survey", "subhypothesis_id": _text(raw.get("subhypothesis_id") or raw.get("idea_id"))},
            )
        )
    return ideas


def _prior_candidate_ideas(candidate: Any) -> List[Dict[str, Any]]:
    if isinstance(candidate, Mapping):
        candidates = candidate.get("candidates") or candidate.get("history") or [candidate]
    else:
        candidates = candidate
    ideas: List[Dict[str, Any]] = []
    for index, item in enumerate(_list(candidates)):
        if not isinstance(item, Mapping) or not item:
            continue
        ideas.append(
            _source_record(
                deepcopy(item),
                "prior_candidate",
                index=index,
                lineage={"source": "history", "candidate_id": _text(item.get("idea_id") or item.get("seed_id"))},
            )
        )
    return ideas


def _experiment_feedback_ideas(results: Any, *, limit: int = 4) -> List[Dict[str, Any]]:
    ideas: List[Dict[str, Any]] = []
    if isinstance(results, Mapping):
        results = results.get("results") or results.get("ablations") or results.get("experiments") or []
    for index, item in enumerate(_list(results)[:limit]):
        if not isinstance(item, Mapping):
            continue
        component = _text(item.get("component") or item.get("name"))
        outcome = _text(item.get("result") or item.get("status") or item.get("hypothesis_status"))
        analysis = _text(item.get("analysis") or item.get("finding") or item.get("summary"))
        if not component and not analysis:
            continue
        ideas.append(
            _source_record(
                {
                    "idea_id": f"experiment-feedback-{index + 1:02d}",
                    "title": f"Experiment feedback: {component or index + 1}",
                    "abstract": analysis or outcome,
                    "hypothesis": f"The observed feedback for {component or 'the candidate'} identifies a mechanism-level refinement.",
                    "scientific_object": component,
                    "mechanism": analysis,
                    "mechanism_or_relation": analysis,
                    "evidence_basis": [analysis, outcome],
                    "falsifier": "A repeated controlled result that removes the reported effect.",
                },
                "experiment_feedback",
                index=index,
                lineage={"source": "ablation_results", "component": component, "outcome": outcome},
            )
        )
    return ideas


def _analysis_source_ideas(analysis: Any) -> List[Dict[str, Any]]:
    if not isinstance(analysis, Mapping):
        return []
    ideas: List[Dict[str, Any]] = []
    groups = (
        ("problem_reframing", "problem_reframing_ideas"),
        ("problem_reframing", "reframed_ideas"),
        ("adversarial_generation", "adversarial_idea_seeds"),
        ("adversarial_generation", "divergent_idea_seeds"),
        ("cross_domain_transfer", "cross_domain_inspiration"),
    )
    counters: Dict[str, int] = {}
    for source, key in groups:
        for raw in _list(analysis.get(key)):
            if not isinstance(raw, Mapping):
                continue
            mapped = dict(raw)
            if source == "cross_domain_transfer":
                mapped.setdefault("title", _text(raw.get("source_field")) or "Cross-domain transfer")
                mapped.setdefault("hypothesis", raw.get("application_hook"))
                mapped.setdefault("mechanism", raw.get("transferable_mechanism"))
                mapped.setdefault("mechanism_or_relation", raw.get("transferable_mechanism"))
                mapped.setdefault("scientific_object", raw.get("source_field"))
            elif source == "adversarial_generation":
                mapped.setdefault("mechanism", raw.get("method_sketch") or raw.get("method"))
                mapped.setdefault("mechanism_or_relation", raw.get("method_sketch") or raw.get("method"))
                mapped.setdefault("falsifier", raw.get("evaluation_plan"))
            elif source == "problem_reframing":
                mapped.setdefault("title", raw.get("reframed_problem") or raw.get("new_question"))
                mapped.setdefault("hypothesis", raw.get("reframed_problem") or raw.get("new_question"))
                mapped.setdefault("mechanism", raw.get("mechanism") or raw.get("mechanism_sketch"))
                mapped.setdefault("mechanism_or_relation", raw.get("mechanism") or raw.get("mechanism_sketch"))
            counters[source] = counters.get(source, 0) + 1
            ideas.append(
                _source_record(
                    mapped,
                    source,
                    index=counters[source] - 1,
                    lineage={"source": "advanced_analysis", "field": key},
                )
            )
    return ideas


def collect_mature_idea_sources(
    *,
    existing: Any = None,
    survey_handoff: Any = None,
    gap_triage: Any = None,
    prior_candidate: Any = None,
    experiment_results: Any = None,
    analysis: Any = None,
    max_ideas: int = 12,
    allow_problem_reframing: bool = True,
    allow_unanchored_seed: bool = True,
    allow_high_risk_seed: bool = True,
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Collect, structurally deduplicate, and annotate mature ideas by lineage."""

    records: List[Dict[str, Any]] = []
    for raw in normalize_mature_ideas(existing, default_source="user_input"):
        records.append(
            _source_record(
                raw,
                _canonical_source(raw.get("idea_source"), "user_input"),
                lineage=raw.get("lineage") or "user_input",
            )
        )
    records.extend(_survey_gap_ideas(survey_handoff, gap_triage))
    records.extend(_survey_subhypothesis_ideas(survey_handoff))
    records.extend(_prior_candidate_ideas(prior_candidate))
    records.extend(_experiment_feedback_ideas(experiment_results))
    records.extend(_analysis_source_ideas(analysis))
    records = [
        annotate_data_anchored_mature_idea(
            record,
            survey_idea_handoff=survey_handoff if isinstance(survey_handoff, Mapping) else {},
            multimodal_evidence_projection=multimodal_evidence_projection,
        )
        for record in records
    ]

    independent = filter_independent_mature_ideas(records)
    enriched: List[Dict[str, Any]] = []
    for record in independent:
        maturity = assess_mature_idea_maturity(record, independent=True)
        record["maturity"] = maturity
        record["maturity_status"] = maturity["maturity_status"]
        record["maturity_is_not_rank"] = True
        source = _canonical_source(record.get("idea_source"), "user_input")
        if not allow_problem_reframing and source == "problem_reframing":
            continue
        if not allow_unanchored_seed and (
            bool(record.get("anti_anchor")) or source in {"problem_reframing", "adversarial_generation"}
        ):
            continue
        if not allow_high_risk_seed and (
            maturity.get("maturity_status") in {"exploratory", "needs_grounding"}
            or _text(record.get("risk")).casefold() in {"high", "major"}
        ):
            continue
        enriched.append(record)
    limit = max(1, int(max_ideas or 12))
    if len(enriched) <= limit:
        return enriched
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    for source in MATURE_IDEA_SOURCES:
        item = next((record for record in enriched if record.get("idea_source") == source), None)
        if item is not None:
            selected.append(item)
            selected_ids.add(id(item))
        if len(selected) >= limit:
            return selected[:limit]
    for item in enriched:
        if id(item) in selected_ids:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def assess_mature_idea_maturity(
    idea: Mapping[str, Any],
    *,
    evidence_context: Mapping[str, Any] | None = None,
    independent: bool = True,
) -> Dict[str, Any]:
    """Score maturity dimensions independently; no single winner is selected."""

    evidence_context = evidence_context if isinstance(evidence_context, Mapping) else {}
    specificity = sum(
        bool(idea.get(field))
        for field in ("title", "hypothesis", "scientific_object", "target_gap_ids")
    ) / 4.0
    mechanism_complete = sum(
        bool(idea.get(field))
        for field in ("mechanism", "mechanism_or_relation", "intervention_or_transformation", "assumptions")
    ) / 4.0
    evidence_support = 1.0 if idea.get("evidence_basis") or evidence_context.get("evidence_subset") else 0.0
    falsifiability = 1.0 if idea.get("falsifier") or idea.get("discriminating_observation") else 0.0
    scope_clarity = 1.0 if idea.get("refinement_scope") or idea.get("claim_scope") else 0.0
    executability = 1.0 if evidence_context.get("validation_targets") or (evidence_support and falsifiability) else 0.0
    independence_score = 1.0 if independent else 0.0
    dimensions = {
        "specificity": round(specificity, 3),
        "mechanism_completeness": round(mechanism_complete, 3),
        "evidence_support": round(evidence_support, 3),
        "falsifiability": round(falsifiability, 3),
        "scope_clarity": round(scope_clarity, 3),
        "executability": round(executability, 3),
        "independence": round(independence_score, 3),
    }
    average = sum(dimensions.values()) / len(dimensions)
    minimum = min(dimensions.values())
    source_status = _text(idea.get("maturity_status")).lower()
    if source_status == "rejected":
        status = "rejected"
    elif average >= 0.68 and minimum >= 0.45:
        status = "mature"
    elif average >= 0.42:
        status = "provisional"
    elif evidence_support == 0.0:
        status = "needs_grounding"
    else:
        status = "exploratory"
    return {
        "dimensions": dimensions,
        "aggregate": round(average, 3),
        "maturity_status": status,
        "maturity_is_not_rank": True,
    }


def build_mature_idea_evidence_context(
    idea: Mapping[str, Any],
    *,
    topic: str = "",
    survey_handoff: Any = None,
    references: Sequence[Mapping[str, Any]] | None = None,
    ablation_results: Any = None,
    public_facts: Any = None,
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Create public, idea-specific, and anti-anchor evidence layers."""

    handoff = dict(survey_handoff) if isinstance(survey_handoff, Mapping) else {}
    source = _canonical_source(idea.get("idea_source"), "user_input")
    anti_anchor = source in {"problem_reframing", "adversarial_generation"} or _text(idea.get("anchor_policy")) == "reframe_without_default_problem_anchor"
    gap_ids = set(_text(item) for item in _list(idea.get("target_gap_ids")))
    gaps = [
        dict(row)
        for row in _gap_rows(handoff)
        if gap_ids and _text(row.get("gap_id")) in gap_ids
    ]
    data_evidence = scoped_multimodal_evidence_for_idea(
        idea,
        survey_idea_handoff=handoff,
        multimodal_evidence_projection=multimodal_evidence_projection,
    )
    keywords = set(
        _text(value).casefold()
        for value in (
            idea.get("title"),
            idea.get("hypothesis"),
            idea.get("mechanism"),
            idea.get("mechanism_or_relation"),
        )
        if _text(value)
    )
    evidence_subset: List[Dict[str, Any]] = []
    target_anchor_ids = {
        _text(anchor_id)
        for gap in gaps
        for anchor_id in _list(gap.get("anchor_ids"))
        if _text(anchor_id)
    }
    scoped_anchors = [
        anchor
        for anchor in _list(handoff.get("anchors"))
        if isinstance(anchor, Mapping)
        and (
            _text(anchor.get("anchor_id")) in target_anchor_ids
            or anchor in data_evidence.get("source_anchors", [])
        )
    ]
    scoped_paper_ids = {
        _text(_mapping(anchor.get("source_pointer")).get("paper_id"))
        for anchor in scoped_anchors
        if _text(_mapping(anchor.get("source_pointer")).get("paper_id"))
    }
    target_subhypotheses_for_papers = {_text(gap.get("subhypothesis_id")) for gap in gaps}
    for role in _list(handoff.get("evidence_roles")):
        if not isinstance(role, Mapping) or _text(role.get("subhypothesis_id")) not in target_subhypotheses_for_papers:
            continue
        scoped_paper_ids.update(
            paper_id
            for paper_id in _unique(
                [
                    role.get("paper_id"),
                    *_list(role.get("paper_ids")),
                    *_list(role.get("qualified_paper_ids")),
                    *_list(role.get("background_paper_ids")),
                ]
            )
            if paper_id
        )
    scoped_paper_ids.update(
        _text(assessment.get("paper_id"))
        for assessment in _list(data_evidence.get("paper_assessments"))
        if isinstance(assessment, Mapping) and _text(assessment.get("paper_id"))
    )
    for reference in references or []:
        if not isinstance(reference, Mapping):
            continue
        ref_text = " ".join(_text(reference.get(field)) for field in ("title", "abstract", "summary", "tldr")).casefold()
        if _text(reference.get("paper_id")) in scoped_paper_ids or any(
            gap_id.casefold() in ref_text for gap_id in gap_ids
        ) or any(
            keyword and keyword in ref_text for keyword in keywords
        ):
            evidence_subset.append(dict(reference))
    evidence_subset = evidence_subset[:8]
    ablation_subset = [
        dict(item)
        for item in _list(ablation_results)
        if isinstance(item, Mapping)
        and idea.get("scientific_object")
        and _text(item.get("component") or item.get("name")).casefold()
        in _text(idea.get("scientific_object")).casefold()
    ][:6]
    scoped_handoff = {
        key: deepcopy(value)
        for key, value in handoff.items()
        if key not in {"gaps", "gap_triage", "source_anchors", "evidence_roles"}
    }
    scoped_handoff["gaps"] = gaps
    raw_gap_triage = handoff.get("gap_triage")
    raw_gap_triage_rows = (
        raw_gap_triage.get("gaps")
        if isinstance(raw_gap_triage, Mapping)
        else raw_gap_triage
    )
    scoped_handoff["gap_triage"] = {
        "gaps": [
            row
            for row in _list(raw_gap_triage_rows)
            if isinstance(row, Mapping)
            and (
                gap_ids and _text(row.get("gap_id")) in gap_ids
            )
        ]
    }
    target_subhypotheses = {_text(gap.get("subhypothesis_id")) for gap in gaps}
    scoped_handoff["anchors"] = [
        deepcopy(anchor)
        for anchor in scoped_anchors
    ]
    scoped_handoff["evidence_roles"] = [
        deepcopy(role)
        for role in _list(handoff.get("evidence_roles"))
        if isinstance(role, Mapping)
        and (
            _text(role.get("subhypothesis_id")) in target_subhypotheses
            or bool(
                set(_unique(role.get("anchor_ids")))
                & {_text(anchor.get("anchor_id")) for anchor in scoped_anchors}
            )
        )
    ]
    result = {
        "public_facts": deepcopy(public_facts) if isinstance(public_facts, (Mapping, list, str)) else {},
        "idea_id": _text(idea.get("idea_id")),
        "idea_source": source,
        "gap_explanation": gaps,
        "evidence_subset": evidence_subset,
        "retrieval_queries": _unique(
            [topic, idea.get("title"), idea.get("hypothesis"), idea.get("mechanism_or_relation")]
        ),
        "counterexamples": _list(idea.get("counterexamples") or idea.get("negative_evidence")) + ablation_subset,
        "mechanism_chain": _unique(
            [idea.get("scientific_object"), idea.get("hypothesis"), idea.get("mechanism_or_relation"), idea.get("falsifier")]
        ),
        "validation_targets": _unique(
            [idea.get("falsifier"), idea.get("discriminating_observation"), idea.get("refinement_scope")]
        ),
        "survey_handoff": scoped_handoff,
        "anchor_policy": "reframe_without_default_problem_anchor" if anti_anchor else "scoped_survey_anchor",
        "anti_anchor": anti_anchor,
        "anti_anchor_reason": (
            "This idea challenges the default problem definition and therefore receives public facts only; "
            "Survey gaps and evidence are included only when explicitly targeted."
            if anti_anchor
            else "Evidence is scoped to the idea's selected gaps and mechanism."
        ),
    }
    if data_evidence:
        result["multimodal_evidence_context"] = data_evidence
        result["counterexamples"] = _list(result["counterexamples"]) + [
            *data_evidence.get("competing_explanations", []),
            *data_evidence.get("claim_limits", []),
        ]
        result["validation_targets"] = _unique(
            [
                *result["validation_targets"],
                *data_evidence.get("measurement_needs", []),
            ]
        )
    return result


__all__ = [
    "MATURE_IDEA_SOURCES",
    "collect_mature_idea_sources",
    "assess_mature_idea_maturity",
    "build_mature_idea_evidence_context",
]
