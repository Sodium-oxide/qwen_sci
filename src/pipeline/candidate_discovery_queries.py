"""Context-preserving discovery queries driven by model semantic judgments."""

from collections.abc import Mapping
import re


CONCEPT_KINDS = {"distinctive_name", "general_property", "evaluation_term", "ambiguous_abbreviation", "unresolved"}
CONTEXT_LEVELS = ("target_system", "source_system", "solution_class")


def short_text(value, words=6):
    return " ".join(re.sub(r"\s+", " ", str(value or "")).strip().split()[:words])[:160]


def discovery_semantics(concepts, anchors, plan=None):
    plan = plan if isinstance(plan, Mapping) else {}
    contexts = []
    for level in CONTEXT_LEVELS:
        for context in plan.get("contexts", []) if isinstance(plan.get("contexts"), list) else []:
            if not isinstance(context, Mapping) or context.get("level") != level:
                continue
            term = short_text(context.get("term")) if isinstance(context.get("term"), str) else ""
            reason = short_text(context.get("reason"), 40) if isinstance(context.get("reason"), str) else ""
            if term and reason and term.casefold() not in {item["term"].casefold() for item in contexts}:
                contexts.append({"level": level, "term": term, "reason": reason})
                break
    if not contexts:
        contexts = [{"level": "target_system" if index == 0 else "source_system", "term": short_text(anchor),
                     "reason": "Unclassified contract context retained"} for index, anchor in enumerate(anchors[:2]) if short_text(anchor)]
    judgments = {}
    for item in plan.get("concepts", []) if isinstance(plan.get("concepts"), list) else []:
        if not isinstance(item, Mapping) or item.get("concept") not in concepts:
            continue
        concept = item["concept"]
        kind = item.get("kind")
        reason = short_text(item.get("reason"), 40) if isinstance(item.get("reason"), str) else ""
        if isinstance(kind, str) and kind in CONCEPT_KINDS and reason and concept not in judgments:
            judgments[concept] = {"kind": kind, "reason": reason, "status": "model_classified"}
    return contexts, judgments


def contextual_query_terms(context, purpose):
    anchor = short_text(context)
    purpose = short_text(purpose, max(1, 12 - len(anchor.split())))
    return [term for term in (anchor, purpose) if term]


def broaden_discovery_lane(lane):
    ladder = lane.get("discovery_context_ladder") or []
    index = int(lane.get("discovery_context_index", 0)) + 1
    if index >= len(ladder) or not lane.get("discovery_query_purpose"):
        return None
    context = ladder[index]
    terms = contextual_query_terms(context["term"], lane["discovery_query_purpose"])
    return {**lane, "lane_id": lane["lane_id"].split(".context_")[0] + f".context_{index}",
            "query": " ".join(terms), "query_variant_terms": terms,
            "discovery_context_index": index, "discovery_context_level": context["level"],
            "context_expansion": True, "provider": "openalex", "lane": "broad_anchor",
            "provider_filter": {}, "hard_filter_applied": False, "discipline_filter_policy": "broad",
            "taxonomy_coverage": "broad",
            "budget_phase": "discovery"}
