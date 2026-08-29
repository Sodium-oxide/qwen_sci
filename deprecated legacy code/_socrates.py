"""Socrates: evidence-bounded mechanism enrichment for research gaps.

Socrates sits between TanXi and MingLi. It does not invent a mechanism. It
turns an incomplete mechanism draft into small, auditable ZhiZhi retrieval
passes, then stores source excerpts for each mechanism field. A missing field
remains explicitly unsupported when the literature does not resolve it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from typing import Any

try:
    from .log import log_event
    from ._input_ontology import classify_input_candidate
    from ._intervention_ontology import (
        classify_intervention_candidate,
        classify_mediator_candidate,
        intervention_gate_from_values,
    )
    from ._research_mode import (
        COMPUTATIONAL_INTERVENTION,
        CONTROLLED_INTERVENTION,
        LABORATORY_CONSTRAINT,
        UNRESOLVED_RESEARCH_DESIGN,
        mode_specific_hypothesis_contract,
        resolve_research_mode,
    )
    from ._outcome_ontology import classify_outcome_candidate
except ImportError:
    from log import log_event
    from _input_ontology import classify_input_candidate
    from _intervention_ontology import (
        classify_intervention_candidate,
        classify_mediator_candidate,
        intervention_gate_from_values,
    )
    from _research_mode import (
        COMPUTATIONAL_INTERVENTION,
        CONTROLLED_INTERVENTION,
        LABORATORY_CONSTRAINT,
        UNRESOLVED_RESEARCH_DESIGN,
        mode_specific_hypothesis_contract,
        resolve_research_mode,
    )
    from _outcome_ontology import classify_outcome_candidate


SOCRATES_MAX_ITERATIONS = 3
SOCRATES_MAX_FIELDS_PER_ITERATION = 2
SOCRATES_MAX_IMPORTS_PER_QUERY = 2
# Socrates supplies evidence used to authorize a causal hypothesis, not an
# exploratory watchlist.  Unpublished preprints may remain in the broader
# PaperGraph, but never enter a Socrates retrieval or satisfy its contract.
# This policy is intentionally domain-neutral: the criterion is publication
# status and source traceability, not a list of field-specific journals.
SOCRATES_PREPRINT_LAYERS: set[str] = set()
DIRECT_EVIDENCE_PREPRINT_LAYERS: set[str] = set()
SOCRATES_PREPRINT_RECOVERY_WINDOWS = (12,)
SOCRATES_PREPRINT_RECOVERY_MAX_VARIANTS = 1
SOCRATES_PREPRINT_MAX_BRANCHES = 1
MECHANISM_FIELDS = (
    "identity",
    "location_or_scope",
    "dynamics",
    "reversibility",
    "observability",
    "intervention",
    "counterfactual",
)
FIELD_ALIASES = {"location": "location_or_scope", "scope": "location_or_scope"}
EVIDENCE_STATES = ("SUPPORTED", "INFERRED", "SPECULATIVE", "CONTRADICTED")
EVIDENCE_GRADES = ("A", "B", "C", "D")

FIELD_QUERY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "identity": (
        "{context} mechanism physical chemical biological origin",
        "{context} defect species phase pathway characterization",
    ),
    "location_or_scope": (
        "{context} interface surface region site spatial localization",
        "{context} boundary layer local distribution mapping",
    ),
    "dynamics": (
        "{context} kinetics rate time evolution accumulation cycle dependence",
        "{context} growth decay threshold temporal evolution model",
    ),
    "reversibility": (
        "{context} reversible irreversible recovery relaxation annealing",
        "{context} restoration hysteresis transient permanent degradation",
    ),
    "observability": (
        "{context} in situ operando measurement characterization detection",
        "{context} spectroscopy microscopy imaging assay observable signal",
    ),
    "intervention": (
        "{context} control manipulation suppression enhancement ablation",
        "{context} intervention blocking perturbation causal experiment",
    ),
    "counterfactual": (
        "{context} control experiment absence without baseline comparison",
        "{context} causal validation negative control mediation test",
    ),
}

FIELD_MARKERS: dict[str, tuple[str, ...]] = {
    "identity": ("mechanism", "pathway", "formation", "origin", "species", "phase", "defect", "reaction"),
    "location_or_scope": ("interface", "surface", "region", "site", "layer", "boundary", "within", "localized"),
    "dynamics": ("kinetic", "rate", "time", "cycle", "accumulation", "growth", "decay", "evolution", "threshold"),
    "reversibility": ("reversible", "irreversible", "recovery", "relaxation", "anneal", "restoration", "hysteresis"),
    "observability": ("measured", "detected", "observed", "characterized", "spectroscopy", "microscopy", "imaging", "assay"),
    "intervention": ("controlled", "suppressed", "enhanced", "inhibited", "ablation", "varied", "manipulated", "perturb"),
    "counterfactual": ("without", "absence", "control", "baseline", "compared", "negative control", "mediation"),
}

_STOPWORDS = {
    "about", "after", "before", "between", "from", "into", "that", "their", "there", "these", "this",
    "with", "when", "where", "which", "while", "using", "used", "study", "studies", "research",
    "method", "methods", "mechanism", "effect", "effects", "system", "systems", "analysis", "approach",
    "cell", "cells", "stem", "biology", "biological", "process", "pathway", "response", "state",
}

_GENERIC_OUTCOME_MARKERS = (
    "prediction of memory outcomes", "prediction of outcomes", "memory outcomes", "biological activity",
    "biological effect", "better memory", "memory outcome", "performance improvement", "overall performance",
    "system performance", "the outcome", "the result", "generic outcome",
)
_GENERIC_CONTRACT_MARKERS = (
    "unresolved", "generic_placeholder", "no intervention candidate", "rationale_only",
    "requires_direct_intervention_evidence", "unknown", "unspecified",
)
_SOURCE_BOUND_FIELD_QUERY_SUFFIXES: dict[str, str] = {
    "identity": "mechanism identity definition direct evidence",
    "location_or_scope": "scope boundary localization direct evidence",
    "dynamics": "parameter dependence temporal response direct evidence",
    "reversibility": "reversibility boundary condition direct evidence",
    "observability": "observable measurement direct evidence",
    "intervention": "intervention perturbation comparison direct evidence",
    "counterfactual": "counterfactual baseline comparison falsification direct evidence",
}
_COMPARISON_MARKERS = (
    " vs ", "versus", "compared", "comparison", "control", "sham", "mock", "vehicle",
    "baseline", "matched", "scrambled", "open-loop", "open loop", "absence", "without",
)
_FALSIFICATION_MARKERS = (
    "falsif", "fail if", "does not", "no change", "unchanged", "null", "reject", "refute",
    "inconsistent", "absent", "not observed", "counterexample", "contradiction",
)


def canonical_mechanism_field(field: str) -> str:
    return FIELD_ALIASES.get(str(field or "").strip().lower(), str(field or "").strip().lower())


def mechanism_candidate_key(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _clean_text(value).lower()))


def mechanism_candidate_is_usable(value: Any) -> bool:
    key = mechanism_candidate_key(value)
    role = classify_mediator_candidate(value)
    return bool(key) and bool(role.get("admissible_as_mediator")) and key not in {
        "mechanism", "pathway", "effect", "outcome", "response", "system", "model", "process", "state",
        "cell", "cells", "stem cell", "protein", "gene", "unknown", "unresolved",
    } and len(key) >= 3


def discover_mediator_candidates(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Enumerate project-grounded mediator candidates without asserting mediation."""
    try:
        from ._gap_detection import canonical_causal_node_key, mechanism_entity_profile
    except ImportError:
        from _gap_detection import canonical_causal_node_key, mechanism_entity_profile
    input_key = canonical_causal_node_key(str(contract.get("input") or ""))
    output_key = canonical_causal_node_key(str(contract.get("output") or ""))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(
        candidate: Any,
        status: str,
        source: str,
        references: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        label = _clean_text(candidate)
        key = mechanism_candidate_key(label)
        if not mechanism_candidate_is_usable(label) or key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "candidate": label,
                "status": status,
                "evidence_grade": "C" if status == "INFERRED" else "D",
                "candidate_source": source,
                "sources": [ref for ref in (references or []) if ref][:6],
                "context": dict(context or {}),
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "observables": [],
                "interpretation": "Candidate only; it is not an established mediator without direct, context-matched evidence.",
            }
        )

    supplied = _clean_text(contract.get("proposed_mediator") or gap.get("proposed_mediator"))
    if mechanism_candidate_is_usable(supplied):
        add_candidate(supplied, "INFERRED", "TanXi/Socrates supplied candidate")
    graph = project.get("causal_evidence_graph", {}) if isinstance(project.get("causal_evidence_graph"), dict) else {}
    nodes = {
        str(node.get("id") or ""): node
        for node in graph.get("nodes", []) if isinstance(node, dict)
    }
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        outgoing.setdefault(str(edge.get("source") or ""), []).append(edge)
    for first in edges:
        source_node = nodes.get(str(first.get("source") or ""), {})
        middle_id = str(first.get("target") or "")
        if input_key and canonical_causal_node_key(str(source_node.get("label") or "")) != input_key:
            continue
        for second in outgoing.get(middle_id, []):
            target_node = nodes.get(str(second.get("target") or ""), {})
            if output_key and canonical_causal_node_key(str(target_node.get("label") or "")) != output_key:
                continue
            middle = nodes.get(middle_id, {})
            references = sorted({str(first.get("citation") or ""), str(second.get("citation") or "")} - {""})
            context = dict(first.get("context") or {}) if isinstance(first.get("context"), dict) else {}
            add_candidate(middle.get("label"), "INFERRED", "project causal graph two-edge path", references, context)
    for item in project.get("ontology_candidates", []) if isinstance(project.get("ontology_candidates"), list) else []:
        if not isinstance(item, dict):
            continue
        labels = [item.get("label"), item.get("entity"), *(item.get("aliases") or [])]
        for label in labels:
            add_candidate(
                label,
                "SPECULATIVE",
                str(item.get("source") or "project ontology candidate"),
                [str(item.get("identifier") or "")],
                item.get("context") if isinstance(item.get("context"), dict) else {},
            )
    profile = mechanism_entity_profile(project)
    for entity in profile.get("entities", [])[:20]:
        if len(candidates) >= limit:
            break
        if input_key and mechanism_candidate_key(entity) == input_key:
            continue
        if output_key and mechanism_candidate_key(entity) == output_key:
            continue
        add_candidate(entity, "SPECULATIVE", "project PaperGraph entity profile")
    return candidates[: max(1, int(limit))]


def enrich_mediator_candidate_evidence(project: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        label = _clean_text(candidate.get("candidate"))
        if not label:
            continue
        lowered_label = label.lower()
        for paper in project.get("papergraph", []):
            if not isinstance(paper, dict) or paper.get("active", True) is False:
                continue
            text = " ".join(str(paper.get(key) or "") for key in ("title", "abstract", "conclusion", "limitation", "full_text_excerpt"))
            if lowered_label not in text.lower():
                continue
            excerpt = next((sentence for sentence in _sentences(text) if lowered_label in sentence.lower()), "")
            entry = {
                "citation": str(paper.get("citation") or paper.get("title") or ""),
                "excerpt": excerpt,
                "context": {"scenario": str(paper.get("scenario") or ""), "method": str(paper.get("method") or "")},
                "evidence_scope": "mechanism_rationale_only" if is_foundational_mechanism_bridge_paper(paper) else "direct_candidate_context",
            }
            lowered = excerpt.lower()
            if any(marker in lowered for marker in ("not mediat", "not causal", "no effect", "failed", "alternative", "independent")):
                candidate["contradicting_evidence"].append(entry)
            else:
                candidate["supporting_evidence"].append(entry)
            observable = str(paper.get("benchmark") or "").strip()
            if observable and observable not in candidate["observables"]:
                candidate["observables"].append(observable)
        candidate["supporting_evidence"] = candidate["supporting_evidence"][:3]
        candidate["contradicting_evidence"] = candidate["contradicting_evidence"][:3]
        candidate["observables"] = candidate["observables"][:5]


def initialize_mechanism_discovery(project: dict[str, Any], gap: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    candidates = discover_mediator_candidates(project, gap, contract)
    enrich_mediator_candidate_evidence(project, candidates)
    current = _clean_text(contract.get("proposed_mediator"))
    if not mechanism_candidate_is_usable(current) and candidates:
        contract["proposed_mediator"] = str(candidates[0]["candidate"])
        contract["identity"] = {
            "candidate": str(candidates[0]["candidate"]),
            "status": str(candidates[0]["status"]),
            "evidence_grade": str(candidates[0]["evidence_grade"]),
            "sources": list(candidates[0].get("sources") or []),
            "context": dict(candidates[0].get("context") or {}),
            "competing_candidates": [item["candidate"] for item in candidates[1:]],
        }
    discovery = {
        "status": "candidate_mediators_identified" if candidates else "mechanism_discovery_required",
        "known": {"input": _clean_text(contract.get("input")), "output": _clean_text(contract.get("output"))},
        "unknown": "Specific mediator identity and its necessity/sufficiency under the stated context.",
        "candidate_mediators": candidates,
        "foundational_mechanism_rationale": foundational_mechanism_rationale(project),
        "next_step": (
            "Search and test the candidates with a direct readout plus a discriminating perturbation."
            if candidates else "Collect a discriminating measurement or perturbation that can reveal candidate mediator identities."
        ),
        "conclusion_boundary": "Candidate mediators are not asserted to mediate the input-output relation until direct, context-matched evidence is found.",
    }
    contract["mechanism_discovery"] = discovery
    contract["candidate_mediators"] = candidates
    return discovery


def is_foundational_mechanism_bridge_paper(paper: dict[str, Any]) -> bool:
    assessment = paper.get("foundational_bridge_assessment")
    return bool(
        isinstance(assessment, dict)
        and assessment.get("bridge_eligible")
        and not assessment.get("eligible_for_primary_gap_evidence")
    )


def foundational_mechanism_rationale(project: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Expose qualified L1 records as rationale, never contract evidence."""
    rationale: list[dict[str, Any]] = []
    for paper in project.get("papergraph", []):
        if not isinstance(paper, dict) or paper.get("active", True) is False:
            continue
        if not is_foundational_mechanism_bridge_paper(paper):
            continue
        assessment = paper.get("foundational_bridge_assessment") or {}
        rationale.append(
            {
                "paper_id": str(paper.get("paper_id") or ""),
                "citation": str(paper.get("citation") or paper.get("title") or ""),
                "title": str(paper.get("title") or ""),
                "bridge_score": ((assessment.get("ranking") or {}).get("foundation_score")),
                "use": "mechanism_rationale_or_competing_mechanism_only",
                "not_direct_target_evidence": True,
                "transfer_assumptions": list(assessment.get("transfer_assumptions") or [])[:2],
            }
        )
    rationale.sort(key=lambda item: -float(item.get("bridge_score") or 0.0))
    return rationale[: max(1, int(limit))]


def evidence_grade_for_entry(entry: dict[str, Any], field: str) -> str:
    evidence_type = str(entry.get("evidence_type") or "").lower()
    source_design = str(entry.get("source_design") or "").lower()
    excerpt = _clean_text(entry.get("excerpt"))
    if source_design in {"review", "systematic_review", "meta_analysis", "perspective"}:
        return "C" if excerpt else "D"
    if field == "intervention" and evidence_type in {"experimental", "genetic", "pharmacological", "interventional"}:
        return "A"
    if evidence_type in {"experimental", "theoretical", "observational"} and excerpt:
        return "B"
    if excerpt:
        return "C"
    return "D"


def socrates_publication_assessment(paper: dict[str, Any]) -> dict[str, Any]:
    """Classify whether a paper can carry a direct Socrates evidence claim.

    Provider labels alone are not a peer-review guarantee, so this deliberately
    uses the conservative, locally available signal: a non-preprint record
    with a formal venue, a non-repository DOI, or a curated scholarly index.
    A high-impact venue improves ranking upstream; it is not a hard gate that
    would make the rule depend on a particular discipline's journal hierarchy.
    """
    try:
        from ._literature_search import has_suspicious_literature_flags, is_preprint_literature_result
    except ImportError:
        from _literature_search import has_suspicious_literature_flags, is_preprint_literature_result

    record = paper if isinstance(paper, dict) else {}
    payload = record.get("papergraph_input") if isinstance(record.get("papergraph_input"), dict) else {}
    provider = _clean_text(record.get("provider") or payload.get("provider")).lower()
    venue = _clean_text(record.get("venue") or payload.get("venue")).lower()
    doi = _clean_text(record.get("doi") or payload.get("doi")).lower()
    preprint = bool(is_preprint_literature_result(record))
    preprint_provider = provider in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}
    repository_venue = venue in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"} or "preprint" in venue
    repository_doi = doi.startswith(("10.1101/", "10.26434/", "10.48550/arxiv."))
    suspicious = bool(has_suspicious_literature_flags(record))
    formal_venue = bool(venue and not repository_venue)
    scholarly_index = provider in {"pubmed", "semantic_scholar", "openalex"}
    formal_doi = bool(doi and not repository_doi)
    eligible = bool(
        not preprint
        and not suspicious
        and (formal_venue or formal_doi or (scholarly_index and not preprint_provider))
    )
    if preprint:
        reason = "unpublished_preprint"
    elif suspicious:
        reason = "suspicious_publication_metadata"
    elif not eligible:
        reason = "formal_publication_metadata_missing"
    else:
        reason = "published_formal_record"
    return {
        "status": reason,
        "provider": provider,
        "is_preprint": preprint,
        "formal_venue": formal_venue,
        "formal_doi": formal_doi,
        "scholarly_index": scholarly_index,
        "eligible_for_direct_contract": eligible,
    }


def socrates_evidence_role(entry: dict[str, Any], paper: dict[str, Any] | None = None) -> str:
    """Give a cited source one broad evidence role for the READY audit."""
    item = entry if isinstance(entry, dict) else {}
    record = paper if isinstance(paper, dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            item.get("excerpt"), item.get("evidence_type"), item.get("source_design"),
            record.get("title"), record.get("abstract"), record.get("study_design"),
        )
    ).lower()
    field = canonical_mechanism_field(str(item.get("field") or ""))
    if any(marker in text for marker in ("theoretical", "theory", "mathematical model", "computational model", "mechanistic model", "simulation", "kinetic model")):
        return "theoretical_or_mechanism_framework"
    if field in {"intervention", "counterfactual"} or any(
        marker in text for marker in ("experimental", "interventional", "randomized", "perturb", "knockout", "ablation", "controlled trial")
    ):
        return "direct_experimental_or_interventional"
    if any(marker in text for marker in ("field demonstration", "pilot project", "monitor", "observational", "cohort", "measurement")):
        return "direct_quantitative_observation"
    return "mechanism_context_only"


def formal_direct_evidence_summary(contract: dict[str, Any]) -> dict[str, Any]:
    """Summarize formal direct evidence lanes without treating L1/reviews as a lane."""
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    formal_entries: list[dict[str, Any]] = []
    for field in MECHANISM_FIELDS:
        for entry in evidence.get(field, []) if isinstance(evidence.get(field), list) else []:
            if not isinstance(entry, dict):
                continue
            assessment = entry.get("publication_assessment") if isinstance(entry.get("publication_assessment"), dict) else {}
            # Tests and externally supplied, audited contracts may use this
            # compact status, while runtime records carry the full assessment.
            eligible = bool(assessment.get("eligible_for_direct_contract")) or str(entry.get("publication_status") or "") == "published_formal_record"
            if eligible and str(entry.get("evidence_scope") or "") != "mechanism_rationale_only":
                formal_entries.append(entry)
    roles = {str(entry.get("evidence_role") or socrates_evidence_role(entry)) for entry in formal_entries}
    formal_text = " ".join(
        " ".join(str(entry.get(key) or "") for key in ("excerpt", "evidence_type", "source_design"))
        for entry in formal_entries
    ).lower()
    return {
        "formal_entry_count": len(formal_entries),
        "theory_or_mechanism_framework": "theoretical_or_mechanism_framework" in roles,
        "direct_experimental_or_interventional": "direct_experimental_or_interventional" in roles,
        "direct_quantitative_observation": "direct_quantitative_observation" in roles,
        "direct_computational_or_simulation": bool(any(marker in formal_text for marker in (
            "simulation", "in silico", "parameter sweep", "feature ablation", "component ablation",
            "counterfactual model", "numerical experiment",
        ))),
        "roles": sorted(roles),
    }


def refresh_mechanism_evidence_ledger(contract: dict[str, Any]) -> dict[str, Any]:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    ledger: dict[str, dict[str, Any]] = {}
    for field in MECHANISM_FIELDS:
        entries = [item for item in evidence.get(field, []) if isinstance(item, dict)]
        if entries and _has_cited_evidence(entries):
            grade = min((evidence_grade_for_entry(item, field) for item in entries), key=EVIDENCE_GRADES.index)
            ledger[field] = {
                "status": "SUPPORTED",
                "evidence_grade": grade,
                "sources": [str(item.get("citation") or "") for item in entries if str(item.get("citation") or "")][:6],
                "context": [item.get("alignment", {}) for item in entries[:3]],
            }
        else:
            current = contract.get(field)
            if isinstance(current, dict) and str(current.get("status") or "") in EVIDENCE_STATES:
                ledger[field] = {
                    "status": str(current.get("status")),
                    "evidence_grade": str(current.get("evidence_grade") or "D"),
                    "sources": list(current.get("sources") or []),
                    "context": current.get("context") or {},
                }
            else:
                ledger[field] = {"status": "SPECULATIVE", "evidence_grade": "D", "sources": [], "context": {}}
    contract["evidence_ledger"] = ledger
    return ledger


def mechanism_discovery_needs_resolution(contract: dict[str, Any]) -> bool:
    ledger = contract.get("evidence_ledger") if isinstance(contract.get("evidence_ledger"), dict) else refresh_mechanism_evidence_ledger(contract)
    return str((ledger.get("identity") or {}).get("status") or "") != "SUPPORTED"


def mechanism_draft_from_gap(gap: dict[str, Any], domain: str = "") -> dict[str, Any]:
    """Create a deliberately incomplete draft without asserting a mechanism."""
    supplied = gap.get("mechanism_draft", {}) if isinstance(gap.get("mechanism_draft"), dict) else {}
    bundle = gap.get("mechanism_evidence_bundle", {}) if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    ingredients = gap.get("hypothesis_ingredients", {}) if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    method = _first_text(ingredients.get("methods"))
    scenario = _first_text(ingredients.get("scenarios"))
    benchmark = _first_text(ingredients.get("benchmarks"))
    description = _clean_text(gap.get("description"))
    context = _clean_text(" ".join(part for part in (method, scenario, domain, description) if part))
    tabi = gap.get("tabi_checks") if isinstance(gap.get("tabi_checks"), dict) else {}
    if tabi and not tabi.get("substantive"):
        # This is a retrieval instruction, not an asserted contradiction. It
        # steers the next Socrates/ZhiZhi passes toward the two evidence types
        # a real TABI audit needs instead of merely filling a matrix hole.
        context = _clean_text(f"{context} theory prediction experimental observation matched conditions")
    raw_input = _clean_text(bundle.get("intervention")) or _clean_text(supplied.get("input")) or method
    mode_resolution = resolve_research_mode(
        {}, gap, {"research_mode": bundle.get("research_mode") or gap.get("research_mode"), "input": raw_input, "context": context}, bundle,
    )
    research_mode = str(mode_resolution.get("mode") or CONTROLLED_INTERVENTION)
    original_audit = gap.get("original_source_role_audit") if isinstance(gap.get("original_source_role_audit"), dict) else {}
    original_input = ((original_audit.get("causal_roles") or {}).get("input") or {}) if isinstance(original_audit.get("causal_roles"), dict) else {}
    input_role = classify_input_candidate(
        raw_input,
        research_mode=research_mode,
        source_unit_ids=list(original_input.get("source_unit_ids") or []),
        require_source_bound=bool(original_audit),
    )
    raw_mediator = _clean_text(bundle.get("mediator")) or _clean_text(supplied.get("proposed_mediator") or gap.get("proposed_mediator") or gap.get("mechanism_hint"))
    mediator_role = classify_mediator_candidate(raw_mediator)
    draft = {
        "gap_id": str(gap.get("gap_id") or ""),
        "research_mode": research_mode,
        "input": raw_input if input_role.get("admissible_as_input") else "unresolved",
        "proposed_mediator": raw_mediator if mediator_role.get("admissible_as_mediator") else "",
        "output": _clean_text(bundle.get("outcome")) or _clean_text(supplied.get("output")) or benchmark,
        "context": context,
        "evidence": {},
        "evidence_policy": {
            "require_published_direct_evidence": True,
            "preprints_are_exploratory_only": True,
            "l1_foundations_are_rationale_only": True,
        },
        "tanxi_mechanism_draft": supplied,
        "mechanism_evidence_bundle": bundle,
        "targeted_evidence_requirements": {
            "status": str(bundle.get("status") or ""),
            "missing_requirements": list(bundle.get("missing_requirements") or []),
            "theory_evidence_ids": list(bundle.get("theory_evidence_ids") or []),
            "experimental_evidence_ids": list(bundle.get("experimental_evidence_ids") or []),
            "computational_evidence_ids": list(bundle.get("computational_evidence_ids") or []),
            "research_mode": research_mode,
            "sub_hypothesis_id": str(bundle.get("sub_hypothesis_id") or gap.get("sub_hypothesis_id") or ""),
            "source_spans": list(bundle.get("mechanism_source_spans") or []),
        },
        "rationale": {
            "source_method": method,
            "source_description": description,
            "source_clue": _clean_text(supplied.get("source_clue")),
        },
        "input_role_assessment": input_role,
        "mediator_role_assessment": mediator_role,
        "tabi_required_retrieval": tabi.get("required_directed_retrieval", []) if tabi else [],
        "mechanism_discovery": {
            "status": "mechanism_discovery_required",
            "known": {"input": _clean_text(supplied.get("input")) or method, "output": _clean_text(supplied.get("output")) or benchmark},
            "unknown": "Specific mediator identity has not yet been established.",
            "candidate_mediators": [],
            "conclusion_boundary": "No mediator is asserted before source-cited, context-matched evidence is available.",
        },
    }
    for field in MECHANISM_FIELDS:
        draft[field] = "unresolved"
    refresh_mechanism_evidence_ledger(draft)
    return draft


def unresolved_mechanism_fields(contract: dict[str, Any]) -> list[str]:
    """Return only fields that lack a source-cited evidence record."""
    evidence = contract.get("evidence", {}) if isinstance(contract.get("evidence"), dict) else {}
    specification = contract.get("mechanism_specification", {}) if isinstance(contract.get("mechanism_specification"), dict) else {}
    unresolved: list[str] = []
    for field in MECHANISM_FIELDS:
        entries = evidence.get(field, [])
        if _has_cited_evidence(entries):
            continue
        value = contract.get(field, specification.get(field))
        if isinstance(value, dict) and _has_cited_evidence(value.get("evidence", [])):
            continue
        unresolved.append(field)
    return unresolved


def check_mechanism_contract_completeness(contract: dict[str, Any]) -> list[str]:
    """Return both evidence-field and hypothesis-readiness deficiencies."""
    normalized = contract if isinstance(contract, dict) else {}
    unresolved = unresolved_mechanism_fields(normalized)
    readiness = mechanism_contract_hypothesis_readiness(normalized)
    return unresolved + [
        f"hypothesis_readiness.{item}"
        for item in readiness.get("missing_requirements", [])
        if f"hypothesis_readiness.{item}" not in unresolved
    ]


def mechanism_contract_value(contract: dict[str, Any], field: str) -> str:
    value = contract.get(field)
    if isinstance(value, dict):
        value = value.get("candidate") or value.get("claim") or value.get("value")
    return _clean_text(value)


def mechanism_output_is_usable(value: Any) -> bool:
    """Accept a compact domain outcome/readout, never a review sentence."""
    text = _clean_text(value)
    lowered = text.lower()
    if not text or lowered in {"unknown", "unspecified", "unresolved", "the outcome"}:
        return False
    if any(marker in lowered for marker in _GENERIC_OUTCOME_MARKERS):
        return False
    role = classify_outcome_candidate(
        text,
        require_target_alignment=False,
        require_source_bound=False,
    )
    return bool(role.get("ontology_valid"))


def mechanism_comparison_is_usable(value: Any) -> bool:
    """Require an actual A/B, intervention/control, or matched null condition."""
    text = _clean_text(value)
    lowered = text.lower()
    if not text or any(marker in lowered for marker in _GENERIC_CONTRACT_MARKERS):
        return False
    return any(marker in lowered for marker in _COMPARISON_MARKERS)


def mechanism_falsification_is_usable(value: Any) -> bool:
    """Require a condition whose failure can be observed in the real world."""
    text = _clean_text(value)
    lowered = text.lower()
    if not text or any(marker in lowered for marker in _GENERIC_CONTRACT_MARKERS):
        return False
    return bool(
        any(marker in lowered for marker in _FALSIFICATION_MARKERS)
        and (mechanism_output_is_usable(text) or any(marker in lowered for marker in _COMPARISON_MARKERS))
    )


def _first_evidence_excerpt(contract: dict[str, Any], field: str) -> str:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    for entry in evidence.get(field, []) if isinstance(evidence.get(field), list) else []:
        if isinstance(entry, dict) and _clean_text(entry.get("excerpt")):
            return _clean_text(entry.get("excerpt"))
    return ""


def _contract_comparison_value(contract: dict[str, Any], gap: dict[str, Any], bundle: dict[str, Any]) -> str:
    return next(
        (
            value for value in (
                _clean_text(contract.get("comparison")),
                _clean_text(bundle.get("comparison")),
                _clean_text(gap.get("comparison")),
                _first_evidence_excerpt(contract, "counterfactual"),
            ) if value
        ),
        "",
    )


def _contract_falsification_value(contract: dict[str, Any], gap: dict[str, Any], bundle: dict[str, Any]) -> str:
    return next(
        (
            value for value in (
                _clean_text(contract.get("falsification")),
                _clean_text(bundle.get("falsification")),
                _clean_text(gap.get("falsification")),
                _first_evidence_excerpt(contract, "counterfactual"),
            ) if value
        ),
        "",
    )


def mechanism_intervention_is_usable(value: Any) -> bool:
    """Require a compact manipulable variable, never a copied result sentence."""
    text = _clean_text(value)
    role = classify_intervention_candidate(text)
    if not role.get("admissible_as_intervention"):
        return False
    # A full abstract/claim sentence can mention a manipulation while still
    # failing to name the independently set factor.  It is not a usable causal
    # input until TanXi/Socrates extracts that compact factor.
    if len(text) > 180 or len(text.split()) > 20:
        return False
    return True


def mechanism_contract_intervention_gate(contract: dict[str, Any]) -> dict[str, Any]:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    ledger = contract.get("evidence_ledger") if isinstance(contract.get("evidence_ledger"), dict) else {}
    intervention_ledger = ledger.get("intervention") if isinstance(ledger.get("intervention"), dict) else {}
    candidates: list[dict[str, Any] | str] = []
    for entry in evidence.get("intervention", []) if isinstance(evidence.get("intervention"), list) else []:
        if not isinstance(entry, dict):
            continue
        candidates.append({
            **entry,
            "candidate": entry.get("excerpt"),
            "evidence_grade": entry.get("evidence_grade") or intervention_ledger.get("evidence_grade"),
            "candidate_source": "socrates.evidence.intervention",
        })
    candidates.append({
        "candidate": mechanism_contract_value(contract, "input"),
        "candidate_source": "socrates.contract.input",
    })
    gate = intervention_gate_from_values(candidates)
    if not gate.get("admissible"):
        return gate
    selected = _clean_text(gate.get("selected_intervention"))
    if not mechanism_intervention_is_usable(selected):
        compact_contract_input = mechanism_contract_value(contract, "input")
        if mechanism_intervention_is_usable(compact_contract_input):
            selected = compact_contract_input
            gate = {
                **gate,
                "selected_intervention": selected,
                "candidate_source": "socrates.contract.input_compact_normalization",
            }
        else:
            return {
                **gate,
                "verdict": "FAIL",
                "admissible": False,
                "selected_intervention": "",
                "reason": "The cited text does not yield a compact, independently manipulable intervention variable.",
            }
    context_terms = _context_terms(
        mechanism_contract_value(contract, "context"),
        mechanism_contract_value(contract, "proposed_mediator"),
        mechanism_contract_value(contract, "output"),
    )
    intervention_terms = _context_terms(selected)
    shared_terms = sorted(context_terms & intervention_terms)
    if context_terms and not shared_terms:
        return {
            **gate,
            "verdict": "FAIL",
            "admissible": False,
            "selected_intervention": "",
            "context_terms": sorted(context_terms)[:30],
            "intervention_terms": sorted(intervention_terms)[:30],
            "shared_context_terms": [],
            "reason": (
                "The candidate is manipulable but does not share a non-generic mechanism/entity anchor "
                "with this Socrates contract. Cross-context interventions cannot seed MingLi."
            ),
        }
    gate["shared_context_terms"] = shared_terms[:12]
    return gate


def evidence_entries_trace_value(entries: Any, value: str) -> bool:
    """Check that a compact causal value is actually present in its source span."""
    target_terms = _context_terms(value)
    if not target_terms:
        return False
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        source_terms = _context_terms(
            str(entry.get("excerpt") or ""),
            str(entry.get("title") or ""),
        )
        if target_terms & source_terms:
            return True
    return False


def core_chain_source_traceability(
    contract: dict[str, Any],
    intervention: str,
    mediator: str,
    outcome: str,
) -> dict[str, bool]:
    """Require source spans for each variable in intervention -> mediator -> outcome."""
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    return {
        "intervention": evidence_entries_trace_value(evidence.get("intervention", []), intervention),
        "mediator": evidence_entries_trace_value(evidence.get("identity", []), mediator),
        "outcome": any(
            evidence_entries_trace_value(evidence.get(field, []), outcome)
            for field in ("observability", "counterfactual", "dynamics")
        ),
    }


def _mode_core_chain_source_traceability(
    contract: dict[str, Any],
    *,
    mode: str,
    input_value: str,
    mediator: str,
    outcome: str,
) -> dict[str, bool]:
    """Trace source spans according to the research design rather than field.

    Controlled/computational work must cite an intervention bucket.  Other
    modes may legitimately put an exposure, premise, calibration condition, or
    sampling plan in another evidence bucket; forcing an ``intervention``
    citation would turn that honest distinction into a false failure.
    """
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    all_entries = [
        entry for field in MECHANISM_FIELDS
        for entry in (evidence.get(field, []) if isinstance(evidence.get(field), list) else [])
        if isinstance(entry, dict)
    ]
    input_entries = (
        evidence.get("intervention", [])
        if mode in {CONTROLLED_INTERVENTION, COMPUTATIONAL_INTERVENTION}
        else all_entries
    )
    return {
        "input_or_design_condition": evidence_entries_trace_value(input_entries, input_value),
        "mediator_or_discriminator": evidence_entries_trace_value(evidence.get("identity", []) or all_entries, mediator),
        "outcome_or_prediction": evidence_entries_trace_value(
            (evidence.get("observability", []) or evidence.get("counterfactual", []) or evidence.get("dynamics", []) or all_entries),
            outcome,
        ),
    }


def _mode_required_evidence_fields(mode: str) -> tuple[str, ...]:
    """Return source buckets required by each epistemic design."""
    if mode in {CONTROLLED_INTERVENTION, COMPUTATIONAL_INTERVENTION}:
        return MECHANISM_FIELDS
    if mode == "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT":
        return ("identity", "dynamics", "observability", "counterfactual")
    if mode == "OBSERVATIONAL_MODEL_DISCRIMINATION":
        return ("identity", "observability", "counterfactual")
    if mode == "INSTRUMENTATION_OR_MEASUREMENT":
        return ("identity", "observability", "counterfactual")
    if mode == LABORATORY_CONSTRAINT:
        return ("identity", "dynamics", "observability", "counterfactual")
    return ("identity", "dynamics")  # formal/theoretical claims


def _mode_has_required_direct_evidence(mode: str, formal_evidence: dict[str, Any]) -> bool:
    if mode == "THEORETICAL_OR_FORMAL":
        return bool(formal_evidence.get("theory_or_mechanism_framework"))
    if mode == COMPUTATIONAL_INTERVENTION:
        return bool(formal_evidence.get("direct_computational_or_simulation"))
    if mode in {
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
        "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "INSTRUMENTATION_OR_MEASUREMENT",
        LABORATORY_CONSTRAINT,
    }:
        return bool(
            formal_evidence.get("direct_quantitative_observation")
            or formal_evidence.get("direct_experimental_or_interventional")
        )
    return bool(formal_evidence.get("direct_experimental_or_interventional"))


def mechanism_contract_hypothesis_readiness(
    contract: dict[str, Any],
    *,
    project: dict[str, Any] | None = None,
    gap: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit a cited contract against its explicit scientific research mode.

    ``CONTROLLED_INTERVENTION`` retains the former strict intervention ->
    mediator -> outcome contract.  Other modes must satisfy their own
    falsifiable design contracts; this is not a relaxed pass, but a refusal to
    mislabel a theorem, a natural experiment, or a telescope observation as a
    wet-lab perturbation.
    """
    normalized = contract if isinstance(contract, dict) else {}
    actual_project = project if isinstance(project, dict) else {}
    actual_gap = gap if isinstance(gap, dict) else {}
    actual_bundle = bundle if isinstance(bundle, dict) else (
        normalized.get("mechanism_evidence_bundle") if isinstance(normalized.get("mechanism_evidence_bundle"), dict) else {}
    )
    evidence = normalized.get("evidence") if isinstance(normalized.get("evidence"), dict) else {}
    ledger = normalized.get("evidence_ledger") if isinstance(normalized.get("evidence_ledger"), dict) else {}
    mode_contract = mode_specific_hypothesis_contract(actual_project, actual_gap, normalized, actual_bundle)
    mode = str(mode_contract.get("mode") or CONTROLLED_INTERVENTION)
    intervention_gate = mechanism_contract_intervention_gate(normalized)
    core_chain = mode_contract.get("normalized_core_chain") if isinstance(mode_contract.get("normalized_core_chain"), dict) else {}
    selected_input = _clean_text(core_chain.get("input_or_intervention"))
    mediator = _clean_text(core_chain.get("mediator") or mechanism_contract_value(normalized, "proposed_mediator") or mechanism_contract_value(normalized, "mediator"))
    outcome = _clean_text(core_chain.get("observable_outcome") or mechanism_contract_value(normalized, "output"))
    identity_status = str((ledger.get("identity") or {}).get("status") or "") if isinstance(ledger.get("identity"), dict) else ""
    formal_evidence = formal_direct_evidence_summary(normalized)
    missing: list[str] = list(mode_contract.get("missing_requirements") or [])
    if not formal_evidence.get("theory_or_mechanism_framework"):
        missing.append("published_theory_or_mechanism_framework")
    if not _mode_has_required_direct_evidence(mode, formal_evidence):
        missing.append("published_mode_appropriate_direct_evidence")
    if mode != "THEORETICAL_OR_FORMAL" and identity_status != "SUPPORTED":
        missing.append("supported_mediator_or_discriminator")
    if not mechanism_output_is_usable(outcome):
        missing.append("observable_or_calculable_outcome")
    unresolved_fields = unresolved_mechanism_fields(normalized)
    mode_unresolved = [field for field in _mode_required_evidence_fields(mode) if field in unresolved_fields]
    if mode_unresolved:
        missing.append("mode_required_evidence_contract")
    source_traceability = _mode_core_chain_source_traceability(
        normalized,
        mode=mode,
        input_value=selected_input,
        mediator=mediator,
        outcome=outcome,
    )
    if not all(source_traceability.values()):
        missing.append("source_traceable_mode_chain")
    missing = list(dict.fromkeys(str(item) for item in missing if str(item).strip()))
    role_assessments = mode_contract.get("role_assessments") if isinstance(mode_contract.get("role_assessments"), dict) else {}
    mediator_role = role_assessments.get("mediator") if isinstance(role_assessments.get("mediator"), dict) else {}
    mediator_ready = (
        bool(mediator_role.get("admissible_as_mediator"))
        if mediator_role
        else is_specific_mechanism_mediator(mediator)
    )
    required = {
        "research_mode_contract": mode_contract.get("status") == "READY",
        "causal_variable": mediator_ready,
        "measurement": bool(
            mechanism_output_is_usable(outcome)
            and (mode == "THEORETICAL_OR_FORMAL" or _has_cited_evidence(evidence.get("observability", [])))
        ),
        "falsification": bool(mode_contract.get("required", {}).get("explicit_falsification", mode_contract.get("status") == "READY")),
        "published_theory_or_mechanism_framework": bool(formal_evidence.get("theory_or_mechanism_framework")),
        "published_mode_appropriate_direct_evidence": _mode_has_required_direct_evidence(mode, formal_evidence),
    }
    # Preserve the legacy audit key as an honest ontology audit.  Non-
    # intervention modes do not require this key to be true for orchestration,
    # but reporting ``True`` merely because another design was inferred hides
    # generic or unresolved input values from state reports.
    input_role = mode_contract.get("role_assessments", {}).get("input", {}) if isinstance(mode_contract.get("role_assessments"), dict) else {}
    required["intervention"] = bool(input_role.get("admissible_as_input"))
    required["published_direct_experiment"] = bool(formal_evidence.get("direct_experimental_or_interventional")) if mode == CONTROLLED_INTERVENTION else True
    return {
        "status": "READY" if not missing else "BLOCKED",
        "contract_status": "READY_FOR_HYPOTHESIS" if not missing else "BLOCKED",
        "ready_for_hypothesis_generation": not missing,
        "research_mode": mode,
        "mode_contract": mode_contract,
        "required": required,
        "missing_requirements": missing,
        "unresolved_evidence_fields": unresolved_fields,
        "mode_unresolved_evidence_fields": mode_unresolved,
        "normalized_core_chain": {
            "input_or_intervention": selected_input,
            "mediator": mediator,
            "observable_outcome": outcome,
        },
        "intervention_type_gate": intervention_gate,
        "formal_direct_evidence": formal_evidence,
        "core_chain_source_traceability": source_traceability,
        "direct_ab_or_intervention_control_ready": bool(
            mode_contract.get("status") == "READY"
            and _has_cited_evidence(evidence.get("observability", []))
            and _has_cited_evidence(evidence.get("counterfactual", []))
        ),
    }


def _contract_original_chain_flags(
    gap: dict[str, Any],
    contract: dict[str, Any],
    bundle: dict[str, Any],
    *,
    research_mode: str = CONTROLLED_INTERVENTION,
) -> list[str]:
    """Reject original TanXi drafts that never named a causal object.

    Socrates may add citations to a promising concrete candidate, but it must
    not make a generic limitation look causal by filling unrelated fields.  A
    missing source span is an evidence-retrieval problem; ``unresolved`` or a
    result sentence in an I/M/O slot is a semantic failure.
    """
    draft = gap.get("mechanism_draft") if isinstance(gap.get("mechanism_draft"), dict) else {}
    tanxi_draft = contract.get("tanxi_mechanism_draft") if isinstance(contract.get("tanxi_mechanism_draft"), dict) else {}
    flags: list[str] = []
    raw_input = _clean_text(
        bundle.get("intervention") or contract.get("input") or draft.get("input") or tanxi_draft.get("input")
        or contract.get("assumptions") or gap.get("assumptions")
    )
    raw_mediator = _clean_text(
        bundle.get("mediator") or draft.get("proposed_mediator") or draft.get("mediator")
        or tanxi_draft.get("proposed_mediator") or tanxi_draft.get("mediator")
    )
    raw_outcome = _clean_text(
        bundle.get("outcome") or draft.get("output") or tanxi_draft.get("output")
    )
    for name, value in (("intervention", raw_input), ("mediator", raw_mediator), ("outcome", raw_outcome)):
        lowered = value.lower()
        if not value or any(marker in lowered for marker in _GENERIC_CONTRACT_MARKERS):
            flags.append(f"original_gap_{name}_unresolved_or_placeholder")
    original_audit = gap.get("original_source_role_audit") if isinstance(gap.get("original_source_role_audit"), dict) else {}
    original_input = ((original_audit.get("causal_roles") or {}).get("input") or {}) if isinstance(original_audit.get("causal_roles"), dict) else {}
    input_role = classify_input_candidate(
        raw_input,
        research_mode=research_mode,
        source_unit_ids=list(original_input.get("source_unit_ids") or []),
        require_source_bound=True,
    )
    if not input_role.get("admissible_as_input"):
        flags.append("original_gap_input_invalid_for_research_mode")
    mediator_role = classify_mediator_candidate(raw_mediator)
    if not mediator_role.get("admissible_as_mediator"):
        flags.append("original_gap_mediator_not_specific")
    if not mechanism_output_is_usable(raw_outcome):
        flags.append("original_gap_outcome_not_measurable")
    # ``rationale_only`` is an explicit role label.  Never infer it from a
    # prose explanation, because rationale may coexist with valid direct
    # evidence; only a causal slot marked rationale-only is disqualifying.
    for value in (draft, tanxi_draft):
        for field in ("input_role_assessment", "mediator_role_assessments", "output_role_assessment"):
            role = value.get(field)
            if isinstance(role, dict) and str(role.get("role") or role.get("category") or "").lower() in {
                "rationale_only", "generic_placeholder", "unresolved", "observation_or_readout",
            } and not (
                research_mode == "OBSERVATIONAL_MODEL_DISCRIMINATION"
                and field == "input_role_assessment"
            ):
                flags.append(f"original_gap_{field}_semantic_role_invalid")
    return list(dict.fromkeys(flags))


def _validate_hypothesis_readiness(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Run the final, entity-level gate before a Socrates contract becomes READY.

    The legacy seven-field ledger is retained as an evidence audit.  This
    gate adds the missing identity checks: one canonical project snapshot,
    one sub-hypothesis, primary-aligned direct evidence, valid causal roles,
    a comparison, and a minimal observable falsifier.  Its state history
    intentionally distinguishes a semantic rejection from a promising gap
    that still needs a bounded retrieval.
    """
    try:
        from ._research_alignment import assess_primary_gap_project_alignment
    except ImportError:
        from _research_alignment import assess_primary_gap_project_alignment

    bundle = (
        contract.get("mechanism_evidence_bundle")
        if isinstance(contract.get("mechanism_evidence_bundle"), dict)
        else gap.get("mechanism_evidence_bundle")
        if isinstance(gap.get("mechanism_evidence_bundle"), dict)
        else {}
    )
    base = mechanism_contract_hypothesis_readiness(contract, project=project, gap=gap, bundle=bundle)
    mode_contract = base.get("mode_contract") if isinstance(base.get("mode_contract"), dict) else {}
    research_mode = str(base.get("research_mode") or mode_contract.get("mode") or CONTROLLED_INTERVENTION)
    topic_alignment = assess_primary_gap_project_alignment(project, gap, bundle)
    source_span_gate = bundle.get("primary_source_span_gate") if isinstance(bundle.get("primary_source_span_gate"), dict) else {}
    source_span_gate_required = str(bundle.get("version") or "").startswith("gap_evidence_bundle_v")
    project_id = str(project.get("project_id") or "")
    gap_project_id = str(gap.get("project_id") or project_id)
    gap_id = str(gap.get("gap_id") or "")
    contract_gap_id = str(contract.get("gap_id") or gap_id)
    gap_sub_id = str(gap.get("sub_hypothesis_id") or "")
    bundle_sub_id = str(bundle.get("sub_hypothesis_id") or gap_sub_id)
    contract_sub_id = str((contract.get("targeted_evidence_requirements") or {}).get("sub_hypothesis_id") or bundle_sub_id)
    snapshot_identity_passes = bool(
        project_id and gap_id and gap_project_id == project_id and contract_gap_id == gap_id
        and gap_sub_id and bundle_sub_id == gap_sub_id and (not contract_sub_id or contract_sub_id == gap_sub_id)
    )
    original_chain_flags = _contract_original_chain_flags(
        gap, contract, bundle, research_mode=research_mode,
    )
    comparison = _contract_comparison_value(contract, gap, bundle)
    falsification = _contract_falsification_value(contract, gap, bundle)
    comparison_passes = mechanism_comparison_is_usable(comparison)
    falsification_passes = mechanism_falsification_is_usable(falsification)
    missing = list(base.get("missing_requirements") or [])
    if not snapshot_identity_passes:
        missing.append("same_project_snapshot_and_subhypothesis")
    topic_missing = list(topic_alignment.get("missing_requirements") or [])
    # No direct record yet is an evidence shortage, not proof that a concrete
    # candidate is off-topic.  Once a direct record exists, however, branch
    # mismatch, failed paper alignment, or zero object anchors is a semantic
    # mismatch and must not be repaired by a generic Socrates search.
    topic_semantic_mismatch = bool(
        topic_alignment.get("branch_mismatch_paper_ids")
        or topic_alignment.get("alignment_failure_paper_ids")
        or (
            topic_alignment.get("direct_evidence_ids")
            and (
                "project_scientific_object_anchor" in topic_missing
                or "subhypothesis_entity_or_relation_anchor" in topic_missing
                or "two_project_local_entity_or_relation_anchors" in topic_missing
            )
        )
    )
    if topic_semantic_mismatch:
        missing.append("project_topic_alignment")
    elif not topic_alignment.get("passes"):
        missing.extend(topic_missing)
    if source_span_gate_required and not bool(source_span_gate.get("passes")):
        missing.append("source_bound_object_process_outcome_evidence")
    # The mode contract owns the comparison semantics for observational,
    # natural, instrumental, and formal work.  Only causal interventions need
    # the legacy A/B wording in addition to that explicit mode contract.
    if research_mode in {CONTROLLED_INTERVENTION, COMPUTATIONAL_INTERVENTION} and not comparison_passes:
        missing.append("direct_ab_or_intervention_control")
    if not falsification_passes:
        missing.append("minimal_falsification_condition")
    missing.extend(original_chain_flags)
    missing = list(dict.fromkeys(str(item) for item in missing if str(item).strip()))
    semantic_failures = [
        item for item in missing
        if item in {
            "same_project_snapshot_and_subhypothesis", "project_topic_alignment",
            "original_gap_intervention_not_operational", "original_gap_computational_transformation_not_operational", "original_gap_mediator_not_specific",
            "original_gap_outcome_not_measurable",
            "original_gap_input_role_assessment_semantic_role_invalid",
            "original_gap_mediator_role_assessments_semantic_role_invalid",
            "original_gap_output_role_assessment_semantic_role_invalid",
            "source_bound_object_process_outcome_evidence",
        }
        or item.endswith("_unresolved_or_placeholder")
    ]
    if not missing:
        state = "READY"
        contract_status = "READY_FOR_HYPOTHESIS"
    elif semantic_failures:
        state = "SEMANTIC_FAIL"
        contract_status = "SEMANTIC_FAIL"
    else:
        state = "NEEDS_TARGETED_SEARCH"
        contract_status = "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
    required = dict(base.get("required") or {})
    required.update({
        "same_project_snapshot_and_subhypothesis": snapshot_identity_passes,
        "project_topic_alignment": bool(topic_alignment.get("passes")),
        "source_bound_primary_evidence": bool(source_span_gate.get("passes")) if source_span_gate_required else True,
        "comparison": comparison_passes if research_mode in {CONTROLLED_INTERVENTION, COMPUTATIONAL_INTERVENTION} else bool(mode_contract.get("required", {}).get("model_discriminator_or_threshold", mode_contract.get("required", {}).get("confounding_or_comparator", True))),
        "minimal_falsification": falsification_passes,
    })
    transitions = [
        "GAP_CREATED",
        "EVIDENCE_AUDIT",
        state,
    ]
    return {
        **base,
        "status": state,
        "contract_status": contract_status,
        "ready_for_hypothesis_generation": state == "READY",
        "required": required,
        "missing_requirements": missing,
        "scientific_readiness_gate": {
            "version": "scientific_hypothesis_readiness_v2",
            "state": state,
            "transitions": transitions,
            "research_mode": research_mode,
            "mode_contract": mode_contract,
            "project_snapshot": {
                "passes": snapshot_identity_passes,
                "project_id": project_id,
                "gap_project_id": gap_project_id,
                "gap_id": gap_id,
                "contract_gap_id": contract_gap_id,
                "gap_sub_hypothesis_id": gap_sub_id,
                "bundle_sub_hypothesis_id": bundle_sub_id,
                "contract_sub_hypothesis_id": contract_sub_id,
            },
            "project_topic_alignment": topic_alignment,
            "primary_source_span_gate": source_span_gate,
            "original_gap_chain_flags": original_chain_flags,
            "comparison": {"value": comparison, "passes": comparison_passes},
            "falsification": {"value": falsification, "passes": falsification_passes},
            "reason": (
                "The source-bound causal chain satisfies the minimum hypothesis contract."
                if state == "READY" else
                "The candidate is semantically invalid and must return to TanXi."
                if state == "SEMANTIC_FAIL" else
                "The candidate is concrete but still lacks source-bounded evidence or a minimal causal test."
            ),
        },
    }


def is_specific_mechanism_mediator(value: Any) -> bool:
    mediator = _clean_text(value).lower()
    if mediator in {"", "unknown", "unspecified", "unresolved", "the proposed mediator"}:
        return False
    generic_markers = (
        "density hole", "no record validates", "no validation", "missing evidence",
        "method-scenario", "coverage gap", "literature gap", "untested",
    )
    if any(marker in mediator for marker in generic_markers):
        return False
    return len(_context_terms(mediator)) >= 1


def socrates_retrieval_ready(
    contract: dict[str, Any],
    *,
    project: dict[str, Any] | None = None,
    gap: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Decide whether a concrete, mode-aware evidence repair is justified."""
    gap_payload = gap if isinstance(gap, dict) else {}
    try:
        from ._scientific_gap_gate import is_causal_scientific_gap
    except ImportError:
        from _scientific_gap_gate import is_causal_scientific_gap
    causal_audit = (
        gap_payload.get("scientific_causal_gap_audit")
        if isinstance(gap_payload.get("scientific_causal_gap_audit"), dict)
        else {}
    )
    if is_causal_scientific_gap(gap_payload) and causal_audit.get("passes_for_socrates") is not True:
        return False, (
            "The causal gap did not pass the atomic-entity, temporal-order, and LLM scientific/actionability audit; "
            "Socrates will not repair or operationalize an invalid causal candidate."
        )
    verification_only = (
        str(gap_payload.get("socrates_retrieval_mode") or "") == "MECHANISM_VERIFICATION_ONLY"
        and gap_payload.get("eligible_for_hypothesis_generation") is False
        and gap_payload.get("may_fill_primary_evidence_slots") is False
    )
    source_bundle = bundle if isinstance(bundle, dict) else {}
    source_span_gate = source_bundle.get("primary_source_span_gate") if isinstance(source_bundle.get("primary_source_span_gate"), dict) else {}
    source_bound_bundle = str(source_bundle.get("version") or "").startswith("gap_evidence_bundle_v")
    invalid_source_states = {
        "OUT_OF_SCOPE_SOURCE", "RATIONALE_ONLY_SOURCE", "SOURCE_ROLE_INVALID",
        "UNRESOLVED_INPUT_ROLE", "UNRESOLVED_OUTPUT_ROLE", "UNRESOLVED_RESEARCH_DESIGN",
        "PARTIAL_SOURCE_ROLE", "UNVERIFIABLE_SOURCE_ROLE", "OUT_OF_SCOPE_SOURCE_OBJECT",
        "THREE_VERDICT_PRIMARY_GATE_FAILED",
    }
    original_audit = (
        source_bundle.get("original_semantic_audit")
        if isinstance(source_bundle.get("original_semantic_audit"), dict)
        else {}
    )
    if not verification_only and (
        (source_bound_bundle and not bool(source_span_gate.get("passes")))
        or str(source_bundle.get("state_reason_code") or "") in invalid_source_states
        or bool(original_audit.get("irreversibly_invalid"))
        or (
            source_bound_bundle
            and source_bundle.get("socrates_targeted_retrieval_allowed") is not True
        )
        or str(source_bundle.get("status") or "") == "SECONDARY_INSUFFICIENT_MECHANISM_MATERIAL"
    ):
        return False, "The original source units do not jointly support the project object, causal process, and outcome; Socrates will not repair a background or off-scope gap."
    mode_contract = mode_specific_hypothesis_contract(
        project if isinstance(project, dict) else {},
        gap if isinstance(gap, dict) else {},
        contract if isinstance(contract, dict) else {},
        bundle if isinstance(bundle, dict) else {},
    )
    mode = str(mode_contract.get("mode") or CONTROLLED_INTERVENTION)
    if mode == UNRESOLVED_RESEARCH_DESIGN:
        return False, "The gap has no source-bound research design, so Socrates will not infer a retrieval strategy from generic method wording."
    input_value = mechanism_contract_value(contract, "input")
    mediator = _clean_text(contract.get("proposed_mediator") or contract.get("mediator"))
    outcome = mechanism_contract_value(contract, "output")
    if not is_specific_mechanism_mediator(mediator):
        return False, "The gap has no concrete proposed mediator; Socrates will not spend retrieval budget on a generic coverage or density-hole query."
    # Retrieval may use a source span as an anchor while TanXi/Socrates is
    # still extracting its compact variable.  The stricter compactness check
    # belongs to the final READY gate, not to the bounded evidence repair.
    provenance = source_bundle.get("causal_field_provenance") if isinstance(source_bundle.get("causal_field_provenance"), dict) else {}
    input_provenance = provenance.get("input") if isinstance(provenance.get("input"), dict) else {}
    outcome_provenance = provenance.get("outcome") if isinstance(provenance.get("outcome"), dict) else {}
    input_role = classify_input_candidate(
        input_value,
        research_mode=mode,
        source_unit_ids=list(input_provenance.get("source_unit_ids") or []),
        require_source_bound=True,
    )
    if not input_role.get("admissible_as_input"):
        return False, "The gap has no source-bound input valid for its research mode, so Socrates will not issue an untargeted query."
    outcome_role = classify_outcome_candidate(
        outcome,
        research_mode=mode,
        target_outcome_terms=[outcome],
        source_unit_ids=list(outcome_provenance.get("source_unit_ids") or []),
        require_target_alignment=False,
        require_source_bound=True,
    )
    if not outcome_role.get("admissible_as_outcome"):
        return False, "The gap has no compact observable outcome, so Socrates will not issue an untargeted mechanism query."
    anchor_groups = (
        _context_terms(input_value, _clean_text(contract.get("context"))),
        _context_terms(mediator),
        _context_terms(outcome),
    )
    if any(not group for group in anchor_groups):
        return False, "The mechanism context must preserve object/intervention, mediator, and observable-outcome anchors before targeted retrieval."
    return True, ""


def _unique_clean_text(values: list[Any], *, limit: int) -> list[str]:
    """Keep complete scientific phrases, rather than truncating their nouns.

    This is intentionally phrase-based.  A query such as ``mineral
    carbonation`` must not be reduced to a bag of generic terms such as
    ``mechanistic`` and ``formation`` before it reaches a provider.
    """
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        if normalized in {"unknown", "unspecified", "unresolved", "the proposed mediator", "the stated outcome"}:
            continue
        seen.add(normalized)
        result.append(cleaned)
        if len(result) >= max(1, int(limit)):
            break
    return result


def direct_evidence_retrieval_anchor_contract(
    contract: dict[str, Any],
    alignment_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a source-bound query contract for a direct-evidence repair.

    A targeted query may use project/sub-hypothesis anchors and causal fields
    that have direct provenance in the bundle.  It must not inherit arbitrary
    prose from a TanXi description, full-text limitation, method, or scenario.
    This is what prevents template residue from becoming provider traffic.
    """
    alignment = alignment_contract if isinstance(alignment_contract, dict) else {}
    bundle = contract.get("mechanism_evidence_bundle") if isinstance(contract.get("mechanism_evidence_bundle"), dict) else {}
    provenance = bundle.get("causal_field_provenance") if isinstance(bundle.get("causal_field_provenance"), dict) else {}
    source_gate = bundle.get("primary_source_span_gate") if isinstance(bundle.get("primary_source_span_gate"), dict) else {}

    def source_bound_value(field: str, *values: Any) -> list[Any]:
        evidence = provenance.get(field) if isinstance(provenance.get(field), dict) else {}
        if evidence and str(evidence.get("source_status") or "") != "DIRECT_SOURCE_SUPPORTED":
            return []
        return [value for value in values if _clean_text(value)]

    system_context = _unique_clean_text(
        [
            alignment.get("focus"),
            *(alignment.get("project_context_phrases") or []),
            *(alignment.get("focus_terms") or []),
        ],
        limit=6,
    )
    intervention = _unique_clean_text(
        source_bound_value("input", contract.get("input")) + list(alignment.get("input_terms") or []),
        limit=6,
    )
    mediator = _unique_clean_text(
        source_bound_value("mediator", contract.get("proposed_mediator") or contract.get("mediator"))
        + list(alignment.get("mechanism_terms") or []) + list(alignment.get("focus_terms") or []),
        limit=7,
    )
    outcome = _unique_clean_text(
        source_bound_value("outcome", contract.get("output")) + list(alignment.get("outcome_terms") or []),
        limit=7,
    )
    # System context and intervention form one object-boundary group.  Some
    # sciences have a named material/organism/system; others are defined by a
    # controlled condition in a well-scoped sub-hypothesis.  Requiring both
    # when available avoids assuming that every field uses the same ontology.
    object_boundary = _unique_clean_text(system_context + intervention, limit=8)
    required_anchor_groups = [group for group in (object_boundary, mediator, outcome) if group]
    source_gate_required = str(bundle.get("version") or "").startswith("gap_evidence_bundle_v")
    source_invalid = bool(source_gate_required and not source_gate.get("passes"))
    allowed_terms = _unique_clean_text(object_boundary + mediator + outcome, limit=32)

    def trusted_items(values: list[str], *, field: str, fallback_provenance: str) -> list[dict[str, Any]]:
        field_provenance = provenance.get(field) if isinstance(provenance.get(field), dict) else {}
        direct_ids = [str(item) for item in (field_provenance.get("source_unit_ids") or []) if str(item)]
        direct_value = _clean_text(field_provenance.get("value"))
        result: list[dict[str, Any]] = []
        for value in values:
            phrase = _clean_text(value)
            if not phrase:
                continue
            is_direct = bool(direct_value and phrase.lower() == direct_value.lower() and direct_ids)
            result.append({
                "phrase": phrase,
                "provenance": "direct_evidence_fragment" if is_direct else fallback_provenance,
                "fragment_ids": direct_ids if is_direct else [],
            })
        return result

    mode = str(bundle.get("research_mode") or contract.get("research_mode") or "")
    return {
        "version": "direct_evidence_retrieval_anchor_contract_v3",
        "sub_hypothesis_id": str(alignment.get("sub_hypothesis_id") or ""),
        "research_mode": mode,
        "system_context": system_context,
        "intervention": intervention,
        "mediator": mediator,
        "outcome": outcome,
        "trusted_object_anchors": trusted_items(
            object_boundary, field="input", fallback_provenance="subhypothesis_alignment_contract",
        ),
        "trusted_process_anchors": trusted_items(
            mediator, field="mediator", fallback_provenance="subhypothesis_alignment_contract",
        ),
        "trusted_outcome_anchors": trusted_items(
            outcome, field="outcome", fallback_provenance="subhypothesis_alignment_contract",
        ),
        # These groups are passed through to provider-safe compaction.  A
        # query is not allowed to silently lose an entire causal axis.
        "required_anchor_groups": required_anchor_groups,
        "allowed_query_terms": allowed_terms,
        "allowed_mode_operator_terms": sorted(
            _mode_specific_operator_tokens(mode)
            | _mode_specific_operator_tokens(mode, "theoretical_framework")
            | _mode_specific_operator_tokens(mode, "computational_evidence")
            | _mode_specific_operator_tokens(mode, "experimental_evidence")
        ),
        "source_bound_primary_gate": source_gate,
        "rejected_untrusted_terms": [],
        "valid": len(required_anchor_groups) == 3 and not source_invalid,
        "invalid_reason": (
            "The original evidence bundle has no direct source unit jointly supporting object, process, and outcome."
            if source_invalid else
            "The repair query lacks one of the object, process, or outcome anchor groups."
            if len(required_anchor_groups) != 3 else ""
        ),
}


def _mode_specific_operator_tokens(mode: str, lane: str = "") -> set[str]:
    """Return generic retrieval operators for one epistemic design.

    These are search-role words rather than scientific entities.  The object,
    process, and outcome must still come from the trusted anchor contract.
    """
    base = {
        "theory", "theoretical", "framework", "mechanism", "model", "study", "and", "or", "in",
        "parameterized", "comparison", "input", "controlled", "observation", "observational",
        "response", "natural", "exposure", "identification", "formal", "prediction",
        "counterexample", "constraint",
        "identity", "definition", "direct", "evidence", "scope", "boundary", "localization",
        "temporal", "dependence", "reversibility", "condition", "observable", "perturbation",
        "counterfactual", "baseline", "falsification",
    }
    by_mode = {
        "COMPUTATIONAL_INTERVENTION": {"parameter", "sweep", "ablation", "numerical", "simulation", "sensitivity", "baseline", "comparison", "silico", "validation"},
        "OBSERVATIONAL_MODEL_DISCRIMINATION": {"competing", "prediction", "observation", "signal", "discriminator", "threshold", "monitoring", "survey"},
        "LABORATORY_CONSTRAINT": {"experiment", "measurement", "quantitative", "constraint", "uncertainty", "propagation", "calibration", "parameter"},
        "INSTRUMENTATION_OR_MEASUREMENT": {"calibration", "response", "function", "error", "uncertainty", "signal", "reference", "measurement"},
        "CONTROLLED_INTERVENTION": {"experiment", "experimental", "intervention", "control", "dose", "condition", "measurement", "quantitative"},
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT": {"natural", "experiment", "exposure", "identification", "comparison", "observational"},
        "THEORETICAL_OR_FORMAL": {"assumption", "derivation", "proof", "theorem", "prediction", "counterexample", "formal"},
    }
    terms = set(base) | set(by_mode.get(str(mode or ""), set()))
    if lane == "experimental_evidence":
        terms |= {"experiment", "experimental", "measurement", "observation", "quantitative"}
    elif lane == "computational_evidence":
        terms |= {"numerical", "simulation", "parameter", "sweep", "ablation", "validation"}
    return terms


def _mode_specific_suffix(mode: str, lane: str) -> str:
    templates = {
        "COMPUTATIONAL_INTERVENTION": {
            "theoretical_framework": "parameterized model mechanism baseline comparison",
            "computational_evidence": "numerical simulation parameter sweep sensitivity baseline validation",
            "experimental_evidence": "quantitative experiment measurement model validation",
        },
        "OBSERVATIONAL_MODEL_DISCRIMINATION": {
            "theoretical_framework": "competing model prediction discriminator threshold",
            "computational_evidence": "numerical competing prediction model comparison",
            "experimental_evidence": "observation signal measurement discriminator threshold",
        },
        "LABORATORY_CONSTRAINT": {
            "theoretical_framework": "parameter constraint uncertainty propagation model input",
            "computational_evidence": "numerical uncertainty propagation parameter sensitivity",
            "experimental_evidence": "quantitative experiment measurement parameter constraint calibration",
        },
        "INSTRUMENTATION_OR_MEASUREMENT": {
            "theoretical_framework": "response function calibration error mechanism",
            "computational_evidence": "numerical response error uncertainty propagation",
            "experimental_evidence": "calibration reference measurement signal uncertainty",
        },
        "CONTROLLED_INTERVENTION": {
            "theoretical_framework": "mechanism framework intervention control",
            "computational_evidence": "model simulation intervention comparison validation",
            "experimental_evidence": "controlled experiment intervention control quantitative measurement",
        },
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT": {
            "theoretical_framework": "identification framework exposure comparison",
            "computational_evidence": "model counterfactual exposure comparison",
            "experimental_evidence": "natural experiment exposure observation comparison",
        },
        "THEORETICAL_OR_FORMAL": {
            "theoretical_framework": "assumption derivation formal prediction counterexample",
            "computational_evidence": "numerical prediction validation counterexample",
            "experimental_evidence": "quantitative observation prediction validation",
        },
    }
    return str(templates.get(str(mode or ""), {}).get(lane) or "theory framework mechanism model")


def build_mode_specific_evidence_queries(
    anchor_contract: dict[str, Any],
    *,
    missing_evidence_lanes: set[str],
) -> list[dict[str, Any]]:
    """Describe bounded source-traceable retrieval lanes for one design mode."""
    mode = str(anchor_contract.get("research_mode") or "")
    result: list[dict[str, Any]] = []
    for lane in ("theoretical_framework", "computational_evidence", "experimental_evidence"):
        if lane not in missing_evidence_lanes:
            continue
        result.append({
            "lane": lane,
            "research_mode": mode,
            "operator_suffix": _mode_specific_suffix(mode, lane),
            "allowed_operator_terms": sorted(_mode_specific_operator_tokens(mode, lane)),
        })
    return result


def validate_socrates_query_provenance(query: str, anchors: dict[str, Any]) -> dict[str, Any]:
    """Verify that every meaningful query token derives from a trusted anchor.

    The suffixes used to request a theory/model/observation evidence lane are
    general retrieval operators and are allowed.  Other informative terms
    must be present in the source-bound anchor contract; unknown residue is
    removed instead of silently widening a Socrates query.
    """
    normalized = _clean_text(query)
    approved_phrases = [str(item).lower() for item in (anchors.get("allowed_query_terms") or []) if str(item).strip()]
    allowed_operator_tokens = set(str(item).lower() for item in (anchors.get("allowed_mode_operator_terms") or []))
    if not allowed_operator_tokens:
        allowed_operator_tokens = _mode_specific_operator_tokens(str(anchors.get("research_mode") or ""))
    allowed_tokens = set()
    for phrase in approved_phrases:
        allowed_tokens.update(re.findall(r"[a-z0-9_+\-./]+", phrase))
    tokens = re.findall(r"[a-z0-9_+\-./]+", normalized.lower())
    rejected = [token for token in tokens if token not in allowed_tokens and token not in allowed_operator_tokens]
    group_presence = []
    for group in anchors.get("required_anchor_groups") or []:
        phrases = [str(item).lower() for item in group if str(item).strip()] if isinstance(group, (list, tuple, set)) else []
        group_presence.append(any(phrase in normalized.lower() for phrase in phrases))
    required_groups_present = bool(group_presence) and all(group_presence)
    return {
        "passes": bool(normalized and anchors.get("valid") and required_groups_present and not rejected),
        "query": normalized,
        "rejected_untrusted_terms": list(dict.fromkeys(rejected))[:16],
        "reason": (
            "Query is compiled only from source-bound/project-contract anchors and evidence-lane operators."
            if normalized and anchors.get("valid") and required_groups_present and not rejected else
            "Query contains untrusted terms or lacks a complete object--process--outcome anchor contract."
        ),
    }


def _direct_evidence_query(
    anchors: dict[str, Any],
    *,
    lane: str,
    recovery: bool,
    max_chars: int = 420,
) -> str:
    """Compile one complete, provider-neutral causal query without slicing words."""
    system_context = [str(item) for item in (anchors.get("system_context") or []) if str(item).strip()]
    intervention = [str(item) for item in (anchors.get("intervention") or []) if str(item).strip()]
    mediator = [str(item) for item in (anchors.get("mediator") or []) if str(item).strip()]
    outcome = [str(item) for item in (anchors.get("outcome") or []) if str(item).strip()]
    if recovery:
        # The recovery is structurally different from the first query: it
        # prefers alignment-contract alternatives, but falls back to the
        # original causal phrase when only one precise term is available.
        system_context = system_context[1:] + system_context[:1]
        intervention = intervention[1:] + intervention[:1]
        mediator = mediator[1:] + mediator[:1]
        outcome = outcome[1:] + outcome[:1]
    suffix = _mode_specific_suffix(str(anchors.get("research_mode") or ""), lane)
    phrases = [
        *(system_context[:1]),
        *(intervention[:1]),
        *(mediator[:2] or mediator[:1]),
        *(outcome[:2] or outcome[:1]),
        suffix,
    ]
    selected: list[str] = []
    used = 0
    for phrase in phrases:
        cleaned = _clean_text(phrase)
        if not cleaned:
            continue
        projected = used + len(cleaned) + (1 if selected else 0)
        if selected and projected > max_chars:
            continue
        selected.append(cleaned)
        used = projected
    compiled = _clean_text(" ".join(selected))
    query_anchors = dict(anchors)
    query_anchors["allowed_mode_operator_terms"] = sorted(_mode_specific_operator_tokens(str(anchors.get("research_mode") or ""), lane))
    provenance = validate_socrates_query_provenance(compiled, query_anchors)
    if provenance.get("passes"):
        return compiled
    anchors["rejected_untrusted_terms"] = provenance.get("rejected_untrusted_terms", [])
    return ""


def evidence_bundle_targeted_retrieval_plan(
    contract: dict[str, Any],
    alignment_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Create two bounded, object-preserving direct-evidence query families.

    This is deliberately separate from the seven Socrates contract fields.
    It repairs a concrete same-sub-hypothesis mechanism candidate that lacks a
    theory/model or experimental side, rather than repeatedly searching a
    generic coverage hole.  Family two is only dispatched after family one
    yields zero imports; it is not an unbounded synonym retry loop.
    """
    requirement = contract.get("targeted_evidence_requirements") if isinstance(contract.get("targeted_evidence_requirements"), dict) else {}
    missing = {str(item) for item in (requirement.get("missing_requirements") or [])}
    if not missing.intersection({"theoretical_framework", "experimental_evidence", "computational_evidence"}):
        return []
    anchors = direct_evidence_retrieval_anchor_contract(contract, alignment_contract)
    if not bool(anchors.get("valid")):
        log_event(
            "SCIENCE",
            "socrates_targeted_query_blocked",
            reason=str(anchors.get("invalid_reason") or "invalid_source_bound_anchor_contract"),
            sub_hypothesis_id=anchors.get("sub_hypothesis_id"),
        )
        return []
    plan: list[dict[str, Any]] = []
    for lane_spec in build_mode_specific_evidence_queries(anchors, missing_evidence_lanes=missing):
        lane = str(lane_spec["lane"])
        for attempt, recovery in ((1, False), (2, True)):
            question = (
                "Which direct theory, model, or mechanism framework links the specified causal chain?"
                if lane == "theoretical_framework" else
                "Which direct numerical experiment, simulation, or parameterized ablation tests the specified transformation and benchmark outcome?"
                if lane == "computational_evidence" else
                "Which direct experiment or quantitative observation tests the specified causal chain?"
            )
            plan.append({
                "lane": lane,
                "attempt": attempt,
                "query_family": "object_mediator_outcome" if not recovery else "alignment_anchor_recovery",
                "query": _direct_evidence_query(anchors, lane=lane, recovery=recovery),
                "question": question,
                "research_mode": lane_spec["research_mode"],
                "query_operator_terms": lane_spec["allowed_operator_terms"],
                "retrieval_anchor_contract": anchors,
            })
    return plan


def direct_evidence_lane_layer_quotas(max_results: int) -> dict[str, int]:
    """Prefer one current top-journal slot while retaining a formal L4 lane.

    The quality preference is not a universal journal whitelist: L2 is a
    small supplement for recent high-quality work, while the remaining L4
    budget keeps mature, field-appropriate primary literature eligible.
    """
    budget = max(1, int(max_results))
    top_latest = 1 if budget >= 3 else 0
    return {
        "L3_preprint": 0,
        "L2_top_latest": top_latest,
        "L0_review": 0,
        "L1_milestone": 0,
        "L4_regular": budget - top_latest,
    }


def direct_evidence_lane_repair_missing_requirements(
    refreshed_bundle: dict[str, Any],
    qualification: dict[str, Any],
) -> list[str]:
    """Return direct evidence lanes still missing after Socrates repair.

    This is intentionally separate from the seven-field mechanism ledger: a
    complete-looking mediator contract cannot turn a candidate with no direct
    theory/model or experiment into a primary hypothesis seed.
    """
    if bool(qualification.get("primary_eligible")):
        return []
    missing = [
        str(item)
        for item in (refreshed_bundle.get("missing_requirements") or [])
        if str(item) in {"theoretical_framework", "experimental_evidence", "computational_evidence"}
    ]
    return missing or ["direct_evidence_lane_not_repaired"]


def compact_socrates_query_context(
    domain: str,
    method: str = "",
    scenario: str = "",
    mediator: str = "",
    context: str = "",
    input_value: str = "",
    outcome: str = "",
) -> str:
    """Build a compact causal retrieval anchor from causal fields only.

    ``method``, ``scenario``, and free-form ``context`` are intentionally not
    appended here.  They often originate in a limitation sentence or a
    malformed extraction and can otherwise leak unrelated template language
    into a source-repair query.  Project/domain scope is supplied by the
    direct-evidence anchor contract on the preferred retrieval path.
    """
    parts: list[str] = []
    cleaned_input = _clean_text(input_value)
    if cleaned_input and classify_intervention_candidate(cleaned_input).get("admissible_as_intervention"):
        parts.append(cleaned_input)
    if is_specific_mechanism_mediator(mediator):
        parts.append(_clean_text(mediator))
    cleaned_outcome = _clean_text(outcome)
    if mechanism_output_is_usable(cleaned_outcome):
        parts.append(cleaned_outcome)
    compact = _clean_text(" ".join(parts))
    return compact[:260]


def translate_unresolved_to_queries(
    unresolved_fields: list[str],
    domain: str,
    method: str = "",
    scenario: str = "",
    mediator: str = "",
    context: str = "",
    input_value: str = "",
    outcome: str = "",
    anchor_contract: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Turn an evidence question into neutral, domain-general query variants."""
    anchors = anchor_contract if isinstance(anchor_contract, dict) else {}
    if anchors:
        if not anchors.get("valid"):
            return {}
        groups = [
            [str(item) for item in group if str(item).strip()]
            for group in (anchors.get("required_anchor_groups") or [])
            if isinstance(group, (list, tuple, set)) and any(str(item).strip() for item in group)
        ]
        if len(groups) != 3:
            return {}
        trusted_context = _clean_text(" ".join(group[0] for group in groups if group))
        queries: dict[str, list[str]] = {}
        for raw_field in unresolved_fields:
            field = canonical_mechanism_field(raw_field)
            suffix = _SOURCE_BOUND_FIELD_QUERY_SUFFIXES.get(field, "")
            query = _clean_text(f"{trusted_context} {suffix}")[:240]
            if not query:
                continue
            audit = validate_socrates_query_provenance(query, anchors)
            if audit.get("passes"):
                queries[field] = [query]
        return queries
    query_context = compact_socrates_query_context(
        domain,
        method=method,
        scenario=scenario,
        mediator=mediator,
        context=context,
        input_value=input_value,
        outcome=outcome,
    )
    if not query_context:
        return {}
    queries: dict[str, list[str]] = {}
    for raw_field in unresolved_fields:
        field = canonical_mechanism_field(raw_field)
        templates = FIELD_QUERY_TEMPLATES.get(field, ())
        variants: list[str] = []
        for template in templates:
            query = _clean_text(template.format(context=query_context))
            if query and query not in variants:
                variants.append(query[:240])
        if variants:
            queries[field] = variants
    return queries


def socrates_field_question(field: str, draft: dict[str, Any]) -> str:
    mediator = _clean_text(draft.get("proposed_mediator")) or "the proposed mediator"
    output = _clean_text(draft.get("output")) or "the stated outcome"
    questions = {
        "identity": f"What concrete physical, chemical, biological, mathematical, or engineering state does '{mediator}' denote, and what source sentence defines it?",
        "location_or_scope": f"Where, in the relevant system or regime, is '{mediator}' reported to act?",
        "dynamics": f"What time, dose, cycle, scale, or parameter dependence links '{mediator}' to {output}?",
        "reversibility": f"Under what recovery, relaxation, reversal, or boundary conditions is '{mediator}' reversible or irreversible?",
        "observability": f"Which measurement or observation directly detects '{mediator}' rather than only {output}?",
        "intervention": f"Which controllable intervention changes '{mediator}' while keeping the comparison interpretable?",
        "counterfactual": f"What control or absence-of-mediator comparison would weaken the claimed link to {output}?",
    }
    return questions.get(field, f"What source evidence resolves the {field} of '{mediator}'?")


def extract_mechanism_evidence(
    project: dict[str, Any],
    target_fields: list[str],
    *,
    domain: str = "",
    method: str = "",
    scenario: str = "",
    mediator: str = "",
    paper_ids: list[str] | None = None,
    max_per_field: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Return only quoted PaperGraph excerpts that match a field and context.

    The returned excerpts are evidence records, not synthesized mechanisms. This
    is the guardrail that keeps Socrates from filling a contract with inference.
    """
    wanted = [canonical_mechanism_field(field) for field in target_fields]
    evidence: dict[str, list[dict[str, Any]]] = {field: [] for field in wanted}
    allowed_ids = {str(item) for item in (paper_ids or []) if str(item)}
    anchors = _context_terms(domain, method, scenario, mediator)
    for paper in project.get("papergraph", []):
        if not isinstance(paper, dict):
            continue
        if paper.get("active", True) is False:
            continue
        # L1 bridges may suggest a mediator or a competing mechanism, but
        # cannot fill any source-cited mechanism-contract field.  Otherwise a
        # cross-domain foundation would silently become direct target evidence.
        if is_foundational_mechanism_bridge_paper(paper):
            continue
        publication = socrates_publication_assessment(paper)
        if not publication.get("eligible_for_direct_contract"):
            # An exploratory preprint or an inadequately identified record can
            # remain in PaperGraph, but it cannot populate a Socrates field.
            continue
        if str(paper.get("retrieval_phase") or "") == "boundary_extension":
            continue
        if str(paper.get("domain_review_verdict") or "keep") in {"review", "reject"}:
            continue
        paper_id = str(paper.get("paper_id") or "")
        if allowed_ids and paper_id not in allowed_ids:
            continue
        source_text = " ".join(
            str(paper.get(key) or "")
            for key in ("title", "abstract", "conclusion", "limitation", "full_text_excerpt")
        )
        alignment = socrates_paper_alignment(project, paper, anchors)
        if not alignment["passes"]:
            continue
        for sentence in _sentences(source_text):
            lowered = sentence.lower()
            anchor_hits = sum(1 for term in anchors if term in lowered)
            for field in wanted:
                marker_hits = sum(1 for marker in FIELD_MARKERS[field] if marker in lowered)
                if marker_hits == 0 or (anchors and anchor_hits == 0):
                    continue
                source_design = socrates_source_design(paper)
                evidence_type = socrates_sentence_evidence_type(paper, sentence, field, source_design)
                record = {
                    "paper_id": paper_id,
                    "citation": str(paper.get("citation") or paper.get("title") or ""),
                    "title": str(paper.get("title") or ""),
                    "field": field,
                    "excerpt": sentence,
                    "score": round(marker_hits * 2 + min(anchor_hits, 3), 2),
                    "alignment": alignment,
                    "source_design": source_design,
                    "evidence_type": evidence_type,
                    "publication_assessment": publication,
                    "publication_status": str(publication.get("status") or ""),
                    "evidence_role": "",
                }
                record["evidence_role"] = socrates_evidence_role(record, paper)
                if field == "intervention":
                    record["intervention_role_assessment"] = classify_intervention_candidate(
                        sentence,
                        evidence_type=evidence_type,
                    )
                evidence[field].append(record)
    for field, entries in evidence.items():
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in entries:
            unique[(entry["citation"], entry["excerpt"])] = entry
        evidence[field] = sorted(unique.values(), key=lambda item: -float(item["score"]))[:max_per_field]
    return evidence


def socrates_source_design(paper: dict[str, Any]) -> str:
    publication_types = paper.get("publicationTypes") or paper.get("publication_types") or []
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    text = " ".join(
        [str(item) for item in publication_types]
        + [str(paper.get("study_design") or ""), str(paper.get("publication_type") or "")]
    ).lower()
    if "systematic review" in text:
        return "systematic_review"
    if "meta-analysis" in text or "meta analysis" in text:
        return "meta_analysis"
    if "review" in text:
        return "review"
    if "perspective" in text or "editorial" in text:
        return "perspective"
    if any(term in text for term in ("randomized", "trial", "experimental", "interventional")):
        return "experimental"
    if any(term in text for term in ("cohort", "observational", "cross-sectional", "case-control")):
        return "observational"
    return "primary_or_unspecified"


def socrates_sentence_evidence_type(
    paper: dict[str, Any],
    sentence: str,
    field: str,
    source_design: str,
) -> str:
    if source_design in {"review", "systematic_review", "meta_analysis", "perspective"}:
        return source_design
    declared = str(paper.get("evidence_type") or paper.get("study_design") or "").lower()
    if any(term in declared for term in ("genetic", "pharmacological", "experimental", "interventional", "trial")):
        return "interventional"
    if "observ" in declared or "cohort" in declared:
        return "observational"
    if field == "intervention" and classify_intervention_candidate(sentence).get("admissible_as_intervention"):
        return "interventional"
    return "observational" if source_design == "observational" else "unspecified"


def socrates_paper_alignment(project: dict[str, Any], paper: dict[str, Any], anchors: set[str]) -> dict[str, Any]:
    """Require evidence papers to share the project-local mechanism vocabulary.

    This catches the tempting but invalid move of filling an ``intervention``
    field with a paper from another application merely because it uses the word
    "control". The vocabulary is learned from the core PaperGraph, not a
    field-specific denylist.
    """
    try:
        from ._gap_detection import mechanism_entity_profile
    except ImportError:
        from _gap_detection import mechanism_entity_profile
    profile = mechanism_entity_profile(project)
    text_terms = _context_terms(" ".join(str(paper.get(field) or "") for field in (
        "title", "abstract", "method", "scenario", "benchmark", "contribution", "limitation",
    )))
    core_hits = sorted(text_terms & set(profile.get("entities", [])))
    anchor_hits = sorted(text_terms & anchors)
    # Two core terms, or one core plus one query/gap anchor, keeps a short but
    # genuinely on-topic paper usable without admitting a broad boundary case.
    passes = len(core_hits) >= 2 or (len(core_hits) >= 1 and len(anchor_hits) >= 1)
    return {"passes": passes, "core_hits": core_hits[:10], "anchor_hits": anchor_hits[:10]}


def socrates_evidence_corpus_signature(project: dict[str, Any]) -> str:
    """Identify the active evidence state without treating report timestamps as new literature."""
    entries = []
    for paper in project.get("papergraph", []):
        if not isinstance(paper, dict) or paper.get("active", True) is False:
            continue
        entries.append(
            "|".join(
                (
                    str(paper.get("paper_id") or ""),
                    str(paper.get("doi") or ""),
                    str(paper.get("title") or ""),
                    str(paper.get("full_text_excerpt") or "")[:160],
                )
            )
        )
    return hashlib.sha1("\n".join(sorted(entries)).encode("utf-8")).hexdigest()[:16]


def prior_socrates_query_keys(
    project: dict[str, Any],
    gap_id: str,
    corpus_signature: str,
) -> set[str]:
    history_root = project.get("socrates_retrieval_history", {})
    history = history_root.get(gap_id, []) if isinstance(history_root, dict) else []
    return {
        normalize_socrates_retrieval_query(item.get("query"))
        for item in history
        if isinstance(item, dict)
        and str(item.get("corpus_signature") or "") == corpus_signature
        and str(item.get("query") or "").strip()
    }


def append_socrates_retrieval_history(
    project: dict[str, Any],
    gap_id: str,
    corpus_signature: str,
    reports: list[dict[str, Any]],
) -> None:
    history_root = project.setdefault("socrates_retrieval_history", {})
    if not isinstance(history_root, dict):
        history_root = {}
        project["socrates_retrieval_history"] = history_root
    history = history_root.setdefault(gap_id, [])
    if not isinstance(history, list):
        history = []
        history_root[gap_id] = history
    known = {
        (str(item.get("corpus_signature") or ""), normalize_socrates_retrieval_query(item.get("query")))
        for item in history
        if isinstance(item, dict)
    }
    for report in reports:
        query = normalize_socrates_retrieval_query(report.get("query"))
        key = (corpus_signature, query)
        if not query or key in known:
            continue
        history.append(
            {
                "field": report.get("field"),
                "query": query,
                "corpus_signature": corpus_signature,
                "search_id": report.get("search_id", ""),
                "result_count": int(report.get("result_count") or 0),
                "imports": int(report.get("imports") or 0),
                "duplicate_candidates": int(report.get("duplicate_candidates") or 0),
                "completed_at": time.time(),
            }
        )
        known.add(key)
    history_root[gap_id] = history[-80:]


def run_socrates_mechanism_enrichment(
    project_id: str,
    gap: dict[str, Any] | str = "",
    gap_id: str = "",
    mechanism_contract: dict[str, Any] | None = None,
    hypothesis_id: str = "",
    post_draft_restricted_bridge: bool = False,
    domain: str = "",
    providers: list[str] | None = None,
    max_iterations: int = SOCRATES_MAX_ITERATIONS,
    max_fields_per_iteration: int = SOCRATES_MAX_FIELDS_PER_ITERATION,
    max_results_per_query: int = 12,
    imports_per_query: int = SOCRATES_MAX_IMPORTS_PER_QUERY,
    use_llm: bool = False,
) -> str:
    """Run bounded Socrates -> ZhiZhi retrieval/enrichment iterations.

    At most ``max_fields_per_iteration`` searches are made per iteration. New
    papers are imported through the normal stratified search store before being
    cited, so every completed field remains traceable to PaperGraph evidence.
    """
    try:
        from ._gap_detection import classify_scientific_gap_track
        from ._project import default_literature_providers, load_project, save_project
        from ._research_workflow import record_workflow_status, socrates_workflow_contract, workflow_tool_gate
    except ImportError:
        from _gap_detection import classify_scientific_gap_track
        from _project import default_literature_providers, load_project, save_project
        from _research_workflow import record_workflow_status, socrates_workflow_contract, workflow_tool_gate

    project = load_project(project_id)
    gate = workflow_tool_gate(
        project,
        "run_socrates_mechanism_enrichment",
        {
            "gap_id": gap_id or (gap.get("gap_id") if isinstance(gap, dict) else gap),
            "mechanism_contract": mechanism_contract or {},
            "hypothesis_id": hypothesis_id,
            "post_draft_restricted_bridge": bool(post_draft_restricted_bridge),
            "domain": domain,
            "providers": list(providers or []),
            "max_iterations": max_iterations,
            "max_fields_per_iteration": max_fields_per_iteration,
            "max_results_per_query": max_results_per_query,
            "imports_per_query": imports_per_query,
            "use_llm": use_llm,
        },
    )
    if not gate.get("allowed"):
        report = dict(gate.get("result") or {})
        report["verdict"] = report.get("status")
        record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report))
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(report, ensure_ascii=False, indent=2)
    try:
        selected_gap = _resolve_gap(project, gap=gap, gap_id=gap_id)
    except ValueError:
        report = {
            "project_id": project_id,
            "gap_id": str(gap_id or ""),
            "verdict": "BLOCKED_INVALID_UPSTREAM_ARTIFACT",
            "terminal": True,
            "reason_code": "UNKNOWN_OR_UNPERSISTED_GAP_ID",
            "allowed_next_stages": [],
            "blocked_stages": ["run_socrates_mechanism_enrichment", "run_mingli_hypothesis_evolution"],
            "searches": 0,
            "imports": 0,
        }
        record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report))
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(report, ensure_ascii=False, indent=2)
    if post_draft_restricted_bridge:
        bridge_route = bool(
            selected_gap.get("restricted_component_bridge_hypothesis_allowed") is True
            or selected_gap.get("component_bridge_gap_synthesis_ready") is True
            or str(selected_gap.get("gap_track") or "") == "COMPONENT_BRIDGE_GAP_SYNTHESIS"
        )
        finalized = next(
            (
                item
                for item in project.get("hypotheses", [])
                if isinstance(item, dict)
                and str(item.get("hypothesis_id") or "") == str(hypothesis_id or "")
            ),
            None,
        )
        if (
            not bridge_route
            or not isinstance(finalized, dict)
            or str(finalized.get("gap_id") or "") != str(selected_gap.get("gap_id") or "")
        ):
            report = {
                "project_id": project_id,
                "gap_id": str(selected_gap.get("gap_id") or ""),
                "hypothesis_id": str(hypothesis_id or ""),
                "verdict": "BLOCKED_INVALID_POST_DRAFT_HANDOFF",
                "reason_code": "POST_DRAFT_SOCRATES_REQUIRES_A_RESTRICTED_BRIDGE_HYPOTHESIS",
                "post_draft_restricted_bridge": False,
                "next_step": "Create a restricted bridge hypothesis before requesting its post-draft Socrates enrichment.",
            }
            report.update(record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report)))
            project.setdefault("socrates_reports", []).append(report)
            project["updatedAt"] = time.time()
            save_project(project)
            return json.dumps(report, ensure_ascii=False, indent=2)
        source_gap = finalized.get("source_gap") if isinstance(finalized.get("source_gap"), dict) else {}
        source_units = [
            str(item.get("source_unit_id") or item.get("paper_id") or "")
            for item in selected_gap.get("source_evidence_units", [])
            if isinstance(item, dict) and str(item.get("source_unit_id") or item.get("paper_id") or "")
        ]
        supporting_references = [
            str(item) for item in selected_gap.get("supporting_references", []) if str(item)
        ]
        mechanism_draft = selected_gap.get("mechanism_draft") if isinstance(selected_gap.get("mechanism_draft"), dict) else {}
        unresolved = [str(item) for item in mechanism_draft.get("unresolved_fields", []) if str(item)]
        disclaimer = str(
            finalized.get("final_object_claim_disclaimer")
            or source_gap.get("final_object_claim_disclaimer")
            or selected_gap.get("final_object_claim_disclaimer")
            or "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。"
        )
        report = {
            "project_id": project_id,
            "gap_id": str(selected_gap.get("gap_id") or ""),
            "hypothesis_id": str(hypothesis_id or ""),
            "verdict": "POST_DRAFT_ENRICHMENT_COMPLETED",
            "post_draft_restricted_bridge": True,
            "enrichment_stage": "AFTER_MINGLI_BEFORE_DEBATE",
            "evidence_dossier": {
                "supporting_references": list(dict.fromkeys(supporting_references)),
                "source_evidence_unit_ids": list(dict.fromkeys(source_units)),
                "unresolved_fields": list(dict.fromkeys(unresolved)),
                "purpose": "Attach the existing component/bridge evidence and explicit uncertainty to the first hypothesis for debate.",
            },
            "final_object_claim_disclaimer": disclaimer,
            "debate_admission": True,
            "next_step": "Enter the Socrates debate with this evidence dossier and retain the final-object claim disclaimer.",
        }
        finalized["final_object_claim_disclaimer"] = disclaimer
        finalized["socrates_post_draft_enrichment"] = {
            "gap_id": report["gap_id"],
            "verdict": report["verdict"],
            "enrichment_stage": report["enrichment_stage"],
            "evidence_dossier": report["evidence_dossier"],
            "final_object_claim_disclaimer": disclaimer,
        }
        report.update(record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report)))
        project.setdefault("socrates_post_draft_enrichments", {})[str(hypothesis_id)] = report
        project.setdefault("socrates_reports", []).append(report)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "socrates_post_draft_restricted_bridge_enrichment_finished",
            project_id=project_id,
            gap_id=report["gap_id"],
            hypothesis_id=hypothesis_id,
        )
        return json.dumps(report, ensure_ascii=False, indent=2)
    # Legacy v2 bundles were created before source-fragment alignment became
    # a primary-gap invariant.  Rebuild them before deciding whether a gap is
    # eligible for Socrates; otherwise an old persisted READY-looking bundle
    # could bypass the new source-bound gate.
    existing_bundle = selected_gap.get("mechanism_evidence_bundle") if isinstance(selected_gap.get("mechanism_evidence_bundle"), dict) else {}
    if str(existing_bundle.get("version") or "") != "gap_evidence_bundle_v5":
        try:
            from ._research_alignment import build_gap_mechanism_evidence_bundle, qualify_gap_for_primary_hypothesis
        except ImportError:
            from _research_alignment import build_gap_mechanism_evidence_bundle, qualify_gap_for_primary_hypothesis
        rebuilt_bundle = build_gap_mechanism_evidence_bundle(project, selected_gap)
        selected_gap["mechanism_evidence_bundle"] = rebuilt_bundle
        selected_gap["alignment_qualification"] = qualify_gap_for_primary_hypothesis(project, selected_gap)
        for collection_name in ("knowledge_gaps",):
            for current in project.get(collection_name, []):
                if isinstance(current, dict) and str(current.get("gap_id") or "") == str(selected_gap.get("gap_id") or ""):
                    current["mechanism_evidence_bundle"] = rebuilt_bundle
                    current["alignment_qualification"] = selected_gap["alignment_qualification"]
        project["updatedAt"] = time.time()
        save_project(project)
    triage = classify_scientific_gap_track(selected_gap)
    bundle = selected_gap.get("mechanism_evidence_bundle") if isinstance(selected_gap.get("mechanism_evidence_bundle"), dict) else {}
    targeted_bundle_candidate = str(bundle.get("status") or "") == "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
    mechanism_verification_only = (
        str(selected_gap.get("socrates_retrieval_mode") or "") == "MECHANISM_VERIFICATION_ONLY"
        and selected_gap.get("may_fill_primary_evidence_slots") is False
    )
    if not triage["eligible_for_hypothesis_generation"] and not targeted_bundle_candidate and not mechanism_verification_only:
        report = {
            "project_id": project_id,
            "gap_id": str(selected_gap.get("gap_id") or ""),
            "gap_track": triage["track"],
            "verdict": "SECONDARY_RESEARCH_OPPORTUNITY",
            "iterations": [],
            "searches": 0,
            "imports": 0,
            "retrieval_skipped": True,
            "retrieval_skip_reason": triage["reason"],
            "next_step": "Use this opportunity to add data, a benchmark, or a measurement layer; rerun TanXi before requesting a mechanism-enrichment search.",
        }
        report.update(record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report)))
        project.setdefault("socrates_reports", []).append(report)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "socrates_secondary_gap_rejected",
            project_id=project_id,
            gap_id=report["gap_id"],
            gap_track=triage["track"],
        )
        return json.dumps(report, ensure_ascii=False, indent=2)
    actual_domain = _clean_text(domain or project.get("domain"))
    resolved_gap_id = str(selected_gap.get("gap_id") or "unassigned")
    prior_contracts = project.get("socrates_mechanism_contracts", {})
    prior_contract = prior_contracts.get(resolved_gap_id) if isinstance(prior_contracts, dict) else None
    if isinstance(mechanism_contract, dict):
        contract = copy.deepcopy(mechanism_contract)
    elif isinstance(prior_contract, dict):
        contract = copy.deepcopy(prior_contract)
    else:
        contract = mechanism_draft_from_gap(selected_gap, actual_domain)
    contract.setdefault("gap_id", resolved_gap_id)
    contract.setdefault("evidence", {})
    contract.setdefault("evidence_policy", {
        "require_published_direct_evidence": True,
        "preprints_are_exploratory_only": True,
        "l1_foundations_are_rationale_only": True,
    })
    contract.setdefault("context", _clean_text(selected_gap.get("description")))
    if isinstance(bundle, dict) and bundle:
        contract.setdefault("mechanism_evidence_bundle", bundle)
        contract.setdefault(
            "targeted_evidence_requirements",
            {
                "status": str(bundle.get("status") or ""),
                "sub_hypothesis_id": str(bundle.get("sub_hypothesis_id") or selected_gap.get("sub_hypothesis_id") or ""),
                "missing_requirements": list(bundle.get("missing_requirements") or []),
                "theory_evidence_ids": list(bundle.get("theory_evidence_ids") or []),
                "experimental_evidence_ids": list(bundle.get("experimental_evidence_ids") or []),
                "source_spans": list(bundle.get("mechanism_source_spans") or []),
            },
        )
        requirements = contract.get("targeted_evidence_requirements") if isinstance(contract.get("targeted_evidence_requirements"), dict) else {}
        requirements.setdefault("sub_hypothesis_id", str(bundle.get("sub_hypothesis_id") or selected_gap.get("sub_hypothesis_id") or ""))
        contract["targeted_evidence_requirements"] = requirements
    for field in MECHANISM_FIELDS:
        contract.setdefault(field, "unresolved")
    discovery = initialize_mechanism_discovery(project, selected_gap, contract)
    refresh_mechanism_evidence_ledger(contract)

    ingredients = selected_gap.get("hypothesis_ingredients", {}) if isinstance(selected_gap.get("hypothesis_ingredients"), dict) else {}
    method = _first_text(ingredients.get("methods"))
    scenario = _first_text(ingredients.get("scenarios"))
    mediator = _clean_text(contract.get("proposed_mediator") or contract.get("mediator"))
    selected_providers = providers or default_literature_providers(domain=actual_domain, query=contract.get("context", ""))
    selected_providers = [str(provider) for provider in selected_providers if str(provider)]
    max_iterations = max(1, min(int(max_iterations or SOCRATES_MAX_ITERATIONS), 5))
    max_fields_per_iteration = max(1, min(int(max_fields_per_iteration or SOCRATES_MAX_FIELDS_PER_ITERATION), 3))
    max_results_per_query = max(5, min(int(max_results_per_query or 12), 30))
    imports_per_query = max(1, min(int(imports_per_query or SOCRATES_MAX_IMPORTS_PER_QUERY), 3))
    verification_only = str(selected_gap.get("socrates_retrieval_mode") or "") == "MECHANISM_VERIFICATION_ONLY"
    if verification_only:
        # This route verifies an already coherent but unverified transmission.
        # It may spend one query and import at most three verification records;
        # the results remain non-primary until TanXi re-audits the gap.
        max_iterations = 1
        max_fields_per_iteration = 1
        max_results_per_query = min(max_results_per_query, 12)
        imports_per_query = min(imports_per_query, 3)
        contract["socrates_retrieval_mode"] = "MECHANISM_VERIFICATION_ONLY"
        contract["may_fill_primary_evidence_slots"] = False
        contract["requires_tanxi_readmission_after_verification"] = True

    retrieval_ready, retrieval_skip_reason = socrates_retrieval_ready(
        contract,
        project=project,
        gap=selected_gap,
        bundle=selected_gap.get("mechanism_evidence_bundle") if isinstance(selected_gap.get("mechanism_evidence_bundle"), dict) else {},
    )
    if not retrieval_ready:
        remaining = unresolved_mechanism_fields(contract)
        causal_inference_plan = build_causal_inference_plan(selected_gap, contract)
        discovery_required = mechanism_discovery_needs_resolution(contract)
        hypothesis_readiness = _validate_hypothesis_readiness(project, selected_gap, contract)
        contract["hypothesis_readiness"] = hypothesis_readiness
        contract["scientific_readiness_gate"] = hypothesis_readiness.get("scientific_readiness_gate", {})
        if discovery_required:
            contract.setdefault("mechanism_discovery", {})["status"] = "mechanism_discovery_required"
        readiness_state = str(hypothesis_readiness.get("status") or "SEMANTIC_FAIL")
        verdict = (
            "SEMANTIC_FAIL"
            if readiness_state == "SEMANTIC_FAIL"
            else "MECHANISM_DISCOVERY_REQUIRED"
            if discovery_required
            else "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
        )
        report = {
            "project_id": project_id,
            "gap_id": resolved_gap_id,
            "mechanism_contract": contract,
            "verdict": verdict,
            "contract_status": verdict,
            "iterations": [],
            "searches": 0,
            "imports": 0,
            "remaining_unresolved": remaining,
            "retrieval_skipped": True,
            "retrieval_skip_reason": retrieval_skip_reason,
            "reading_focus": _reading_focus(remaining),
            "causal_inference_plan": causal_inference_plan,
            "next_step": (
                "Reject this primary-gap candidate: its original causal roles or project object are semantically invalid."
                if verdict == "SEMANTIC_FAIL" else
                "Run a candidate-mediator discovery experiment, simulation, or discriminating measurement; do not claim a specific mediator."
                if discovery_required else "Return this gap to TanXi: define a concrete, source-grounded mediator before Socrates performs a targeted evidence search."
            ),
        }
        report.update(record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report)))
        contract["socrates_enrichment"] = {
            "verdict": verdict,
            "iterations_run": 0,
            "searches": 0,
            "imports": 0,
            "remaining_unresolved": remaining,
            "retrieval_skipped": True,
            "reason": retrieval_skip_reason,
        }
        contract["causal_inference_plan"] = causal_inference_plan
        contract["contract_status"] = verdict
        project.setdefault("socrates_mechanism_contracts", {})[resolved_gap_id] = contract
        project.setdefault("socrates_reports", []).append(report)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "socrates_retrieval_skipped",
            project_id=project_id,
            gap_id=resolved_gap_id,
            reason=retrieval_skip_reason,
        )
        return json.dumps(report, ensure_ascii=False, indent=2)

    # A concrete TanXi bundle with a missing direct lane is eligible for a
    # *bounded*, lane-specific repair before the normal seven-field mechanism
    # audit.  It never grants MingLi access by itself.
    direct_lane_reports: list[dict[str, Any]] = []
    direct_lane_missing_requirements: list[str] = []
    project_contracts = project.get("subhypothesis_alignment_contracts", {}) if isinstance(project.get("subhypothesis_alignment_contracts"), dict) else {}
    bundle_sub_id = str(bundle.get("sub_hypothesis_id") or selected_gap.get("sub_hypothesis_id") or "")
    alignment_contract = project_contracts.get(bundle_sub_id) if isinstance(project_contracts.get(bundle_sub_id), dict) else None
    lane_plan = evidence_bundle_targeted_retrieval_plan(contract, alignment_contract)
    plans_by_lane: dict[str, list[dict[str, Any]]] = {}
    for lane_request in lane_plan:
        plans_by_lane.setdefault(str(lane_request.get("lane") or ""), []).append(lane_request)
    for lane, lane_requests in plans_by_lane.items():
        for request_index, lane_request in enumerate(lane_requests):
            # A second query family is a bounded recovery for a provider miss,
            # alignment rejection, or import failure.  It is not sent after a
            # useful direct candidate has already been imported.
            if request_index and any(
                int(item.get("imports") or 0) > 0
                for item in direct_lane_reports
                if str(item.get("lane") or "") == lane
            ):
                break
            report = socrates_call_zhizhi_targeted_search(
                project_id=project_id,
                query=str(lane_request["query"]),
                domain=actual_domain,
                field=f"direct_{lane}",
                question=str(lane_request["question"]),
                providers=selected_providers,
                max_results=max_results_per_query,
                imports_per_query=imports_per_query,
                use_llm=use_llm,
                # Direct theory and direct experiment repair must not be
                # satisfied by a mandatory latest-preprint quota.
                preprint_layers=DIRECT_EVIDENCE_PREPRINT_LAYERS,
                layer_quotas=direct_evidence_lane_layer_quotas(max_results_per_query),
                alignment_contract=alignment_contract,
                # Computational evidence is retrieved through the theoretical/
                # model lane for provider alignment, but remains labelled as a
                # separate Socrates repair lane and is recognized from its
                # simulation/ablation genre in the rebuilt evidence bundle.
                evidence_kind_override="theoretical_framework" if lane == "computational_evidence" else lane,
                query_branch_override=f"{bundle_sub_id}:{'theoretical_framework' if lane == 'computational_evidence' else lane}" if bundle_sub_id else lane,
                retrieval_anchor_contract=lane_request.get("retrieval_anchor_contract"),
            )
            report["lane"] = lane
            report["attempt"] = int(lane_request.get("attempt") or request_index + 1)
            report["query_family"] = str(lane_request.get("query_family") or "")
            direct_lane_reports.append(report)
            log_event(
                "SCIENCE",
                "socrates_direct_evidence_lane_complete",
                project_id=project_id,
                gap_id=resolved_gap_id,
                sub_hypothesis_id=bundle_sub_id,
                lane=lane,
                attempt=report["attempt"],
                query_family=report["query_family"],
                searches=report.get("searches", 0),
                imports=report.get("imports", 0),
                retrieval_outcome=report.get("retrieval_outcome", ""),
                target_aligned_candidates=report.get("target_aligned_candidates", 0),
            )
            # The plan contains exactly two attempts per lane.  Continue to
            # the second only after the first produced no imported record.
            if int(report.get("imports") or 0) > 0:
                break
    if direct_lane_reports:
        try:
            from ._research_alignment import build_gap_mechanism_evidence_bundle, qualify_gap_for_primary_hypothesis
        except ImportError:
            from _research_alignment import build_gap_mechanism_evidence_bundle, qualify_gap_for_primary_hypothesis
        project = load_project(project_id)
        refreshed_bundle = build_gap_mechanism_evidence_bundle(project, selected_gap)
        selected_gap["mechanism_evidence_bundle"] = refreshed_bundle
        selected_gap["alignment_qualification"] = qualify_gap_for_primary_hypothesis(project, selected_gap)
        direct_lane_missing_requirements = direct_evidence_lane_repair_missing_requirements(
            refreshed_bundle,
            selected_gap["alignment_qualification"],
        )
        contract["targeted_evidence_requirements"]["post_retrieval_bundle"] = refreshed_bundle
        contract["mechanism_evidence_bundle"] = refreshed_bundle
        for collection_name in ("knowledge_gaps",):
            for current in project.get(collection_name, []):
                if isinstance(current, dict) and str(current.get("gap_id") or "") == resolved_gap_id:
                    current["mechanism_evidence_bundle"] = refreshed_bundle
                    current["alignment_qualification"] = selected_gap["alignment_qualification"]
        tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
        for current in tanxi.get("ranked_gaps", []) if isinstance(tanxi.get("ranked_gaps"), list) else []:
            if isinstance(current, dict) and str(current.get("gap_id") or "") == resolved_gap_id:
                current["mechanism_evidence_bundle"] = refreshed_bundle
                current["alignment_qualification"] = selected_gap["alignment_qualification"]
        project["updatedAt"] = time.time()
        save_project(project)

    iterations: list[dict[str, Any]] = []
    searches = sum(int(item.get("searches") or 0) for item in direct_lane_reports)
    imports = sum(int(item.get("imports") or 0) for item in direct_lane_reports)
    attempted_queries: set[tuple[str, str]] = set()
    corpus_signature = socrates_evidence_corpus_signature(project)
    attempted_retrieval_queries = prior_socrates_query_keys(project, resolved_gap_id, corpus_signature)
    skipped_previously_attempted_queries = len(attempted_retrieval_queries)
    normal_mechanism_retrieval_iterations = max_iterations
    if direct_lane_missing_requirements:
        # Do not follow a failed, object-specific direct-evidence repair with
        # broad seven-field searches.  The candidate is already ineligible for
        # MingLi, and generic fields such as "mechanism" or "measurement"
        # would merely reproduce the off-topic traffic that the direct lane
        # just diagnosed.  The persisted direct-lane reports explain exactly
        # which evidence side remains absent.
        normal_mechanism_retrieval_iterations = 0
        log_event(
            "SCIENCE",
            "socrates_generic_mechanism_retrieval_skipped",
            project_id=project_id,
            gap_id=resolved_gap_id,
            reason="direct_evidence_lane_unresolved",
            missing_requirements=direct_lane_missing_requirements,
        )
    mechanism_query_anchor_contract = direct_evidence_retrieval_anchor_contract(contract, alignment_contract)
    if normal_mechanism_retrieval_iterations and not mechanism_query_anchor_contract.get("valid"):
        normal_mechanism_retrieval_iterations = 0
        log_event(
            "SCIENCE",
            "socrates_generic_mechanism_retrieval_skipped",
            project_id=project_id,
            gap_id=resolved_gap_id,
            reason="invalid_source_bound_query_contract",
        )
    for iteration in range(1, normal_mechanism_retrieval_iterations + 1):
        project = load_project(project_id)
        validate_mechanism_contract_evidence(project, contract)
        unresolved = unresolved_mechanism_fields(contract)
        if not unresolved:
            break

        # First, mine what ZhiZhi has already imported before spending a query.
        existing = extract_mechanism_evidence(
            project, unresolved, domain=actual_domain, method=method, scenario=scenario, mediator=mediator,
        )
        updated_from_existing = _apply_evidence(contract, existing)
        validate_mechanism_contract_evidence(project, contract)
        unresolved = unresolved_mechanism_fields(contract)
        query_plan = translate_unresolved_to_queries(
            unresolved,
            actual_domain,
            method,
            scenario,
            mediator,
            str(contract.get("context") or ""),
            input_value=mechanism_contract_value(contract, "input"),
            outcome=mechanism_contract_value(contract, "output"),
            anchor_contract=mechanism_query_anchor_contract,
        )
        selected_queries = select_untried_socrates_queries(
            unresolved,
            query_plan,
            attempted_queries,
            max_fields_per_iteration,
            attempted_retrieval_queries=attempted_retrieval_queries,
        )
        if not selected_queries:
            log_event(
                "SCIENCE",
                "socrates_no_untried_queries",
                project_id=project_id,
                gap_id=resolved_gap_id,
                corpus_signature=corpus_signature,
                prior_query_count=len(attempted_retrieval_queries),
            )
            break
        search_reports: list[dict[str, Any]] = []
        updated_from_new = 0

        for field, query in selected_queries:
            attempted_queries.add((field, query))
            attempted_retrieval_queries.add(normalize_socrates_retrieval_query(query))
            question = socrates_field_question(field, contract)
            report = socrates_call_zhizhi_targeted_search(
                project_id=project_id,
                query=query,
                domain=actual_domain,
                field=field,
                question=question,
                providers=selected_providers,
                max_results=max_results_per_query,
                imports_per_query=imports_per_query,
                use_llm=use_llm,
                preprint_layers=DIRECT_EVIDENCE_PREPRINT_LAYERS,
                layer_quotas=direct_evidence_lane_layer_quotas(max_results_per_query),
                alignment_contract=alignment_contract,
                retrieval_anchor_contract=mechanism_query_anchor_contract,
            )
            searches += int(report.get("searches", 0))
            imports += int(report.get("imports", 0))
            search_reports.append(report)
            project = load_project(project_id)
            new_evidence = extract_mechanism_evidence(
                project, [field], domain=actual_domain, method=method, scenario=scenario,
                mediator=mediator, paper_ids=report.get("paper_ids", []),
            )
            updated_from_new += _apply_evidence(contract, new_evidence)
            validate_mechanism_contract_evidence(project, contract)

        validate_mechanism_contract_evidence(project, contract)
        remaining = unresolved_mechanism_fields(contract)
        iteration_report = {
            "iteration": iteration,
            "unresolved_at_start": unresolved,
            "questions": {field: socrates_field_question(field, contract) for field, _ in selected_queries},
            "search_reports": search_reports,
            "fields_resolved_from_existing_papers": updated_from_existing,
            "fields_resolved_from_new_papers": updated_from_new,
            "remaining_unresolved": remaining,
        }
        iterations.append(iteration_report)
        log_event(
            "SCIENCE", "socrates_iteration_complete", project_id=project_id, iteration=iteration,
            searches=sum(item.get("searches", 0) for item in search_reports), imports=sum(item.get("imports", 0) for item in search_reports),
            resolved=updated_from_existing + updated_from_new, remaining=len(remaining),
        )
        queries_remain = any(
            any(
                (field, query) not in attempted_queries
                and normalize_socrates_retrieval_query(query) not in attempted_retrieval_queries
                for query in query_plan.get(field, [])
            )
            for field in remaining
        )
        if updated_from_existing + updated_from_new == 0 and not queries_remain:
            break

    project = load_project(project_id)
    validate_mechanism_contract_evidence(project, contract)
    refresh_mechanism_evidence_ledger(contract)
    remaining = unresolved_mechanism_fields(contract)
    causal_inference_plan = build_causal_inference_plan(selected_gap, contract)
    contract["causal_inference_plan"] = causal_inference_plan
    hypothesis_readiness = _validate_hypothesis_readiness(project, selected_gap, contract)
    if direct_lane_missing_requirements:
        # A successful-looking seven-field mechanism ledger cannot erase a
        # failed repair of the missing same-sub-hypothesis direct theory or
        # experiment lane.  Preserve the exact missing lane so this contract
        # cannot be accidentally routed to MingLi as a false READY state.
        hypothesis_readiness = dict(hypothesis_readiness)
        hypothesis_readiness["status"] = "NEEDS_TARGETED_SEARCH"
        hypothesis_readiness["contract_status"] = "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
        hypothesis_readiness["ready_for_hypothesis_generation"] = False
        hypothesis_readiness["missing_requirements"] = list(dict.fromkeys(
            [str(item) for item in (hypothesis_readiness.get("missing_requirements") or [])]
            + direct_lane_missing_requirements
        ))
        contract["direct_evidence_lane_gate"] = {
            "status": "FAILED_TO_REPAIR",
            "missing_requirements": list(direct_lane_missing_requirements),
            "reports": direct_lane_reports,
        }
        remaining = list(dict.fromkeys([str(item) for item in remaining] + direct_lane_missing_requirements))
    elif direct_lane_reports:
        contract["direct_evidence_lane_gate"] = {
            "status": "REPAIRED",
            "missing_requirements": [],
            "reports": direct_lane_reports,
        }
    contract["hypothesis_readiness"] = hypothesis_readiness
    contract["scientific_readiness_gate"] = hypothesis_readiness.get("scientific_readiness_gate", {})
    if hypothesis_readiness.get("ready_for_hypothesis_generation"):
        normalized_input = str(
            (hypothesis_readiness.get("normalized_core_chain") or {}).get("input_or_intervention") or ""
        ).strip()
        if normalized_input:
            contract["input"] = normalized_input
    discovery_status = str((contract.get("mechanism_discovery") or {}).get("status") or "")
    if remaining and mechanism_discovery_needs_resolution(contract):
        contract.setdefault("mechanism_discovery", {})["status"] = "mechanism_discovery_required"
        discovery_status = "mechanism_discovery_required"
    readiness_state = str(hypothesis_readiness.get("status") or "NEEDS_TARGETED_SEARCH")
    verdict = (
        "READY_FOR_HYPOTHESIS"
        if readiness_state == "READY" and not remaining and not direct_lane_missing_requirements
        else "SEMANTIC_FAIL"
        if readiness_state == "SEMANTIC_FAIL"
        else "MECHANISM_DISCOVERY_REQUIRED"
        if discovery_status == "mechanism_discovery_required"
        and "supported_mediator" in hypothesis_readiness.get("missing_requirements", [])
        else "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
    )
    if verification_only:
        hypothesis_readiness = {
            **hypothesis_readiness,
            "status": "REQUIRES_TANXI_READMISSION",
            "contract_status": "MECHANISM_VERIFICATION_COMPLETED_PENDING_TANXI_READMISSION",
            "ready_for_hypothesis_generation": False,
        }
        contract["hypothesis_readiness"] = hypothesis_readiness
        verdict = "MECHANISM_VERIFICATION_COMPLETED_PENDING_TANXI_READMISSION"
    report = {
        "project_id": project_id,
        "gap_id": str(selected_gap.get("gap_id") or ""),
        "mechanism_contract": contract,
        "verdict": verdict,
        "contract_status": verdict,
        "socrates_retrieval_mode": (
            "MECHANISM_VERIFICATION_ONLY" if verification_only else "GAP_ENRICHMENT"
        ),
        "may_fill_primary_evidence_slots": not verification_only,
        "requires_tanxi_readmission": verification_only,
        "iterations": iterations,
        "direct_evidence_lane_reports": direct_lane_reports,
        "searches": searches,
        "imports": imports,
        "corpus_signature": corpus_signature,
        "skipped_previously_attempted_queries": skipped_previously_attempted_queries,
        "remaining_unresolved": remaining,
        "hypothesis_readiness": hypothesis_readiness,
        "reading_focus": _reading_focus(remaining),
        "causal_inference_plan": causal_inference_plan,
        "next_step": (
            "Return the verification evidence to TanXi for source-bound readmission; do not pass this lead directly to MingLi."
            if verification_only
            else "Pass this evidence-cited, intervention-ready mechanism contract to MingLi."
            if verdict == "READY_FOR_HYPOTHESIS"
            else (
                "Do not pass this contract to MingLi. Resolve the missing hypothesis-readiness requirements: "
                + ", ".join(hypothesis_readiness.get("missing_requirements", []))
                + "."
            )
        ),
    }
    contract["socrates_enrichment"] = {
        "verdict": verdict,
        "iterations_run": len(iterations),
        "direct_evidence_lane_reports": direct_lane_reports,
        "searches": searches,
        "imports": imports,
        "remaining_unresolved": remaining,
        "hypothesis_readiness": hypothesis_readiness,
    }
    contract["contract_status"] = verdict
    project = load_project(project_id)
    append_socrates_retrieval_history(project, resolved_gap_id, corpus_signature, [
        item
        for iteration in iterations
        for item in iteration.get("search_reports", [])
        if isinstance(item, dict)
    ])
    project.setdefault("socrates_mechanism_contracts", {})[resolved_gap_id] = contract
    project.setdefault("socrates_reports", []).append(report)
    report.update(record_workflow_status(project, stage="socrates", **socrates_workflow_contract(report)))
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "socrates_enrichment_finished", project_id=project_id, verdict=verdict, searches=searches, imports=imports, remaining=len(remaining))
    persisted_report = next(
        (
            item for item in reversed(project.get("socrates_reports", []))
            if isinstance(item, dict) and str(item.get("gap_id") or "") == resolved_gap_id
        ),
        report,
    )
    return json.dumps(persisted_report, ensure_ascii=False, indent=2)


def build_causal_inference_plan(gap: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    ledger = contract.get("evidence_ledger") if isinstance(contract.get("evidence_ledger"), dict) else {}
    intervention_ledger = ledger.get("intervention") if isinstance(ledger.get("intervention"), dict) else {}
    intervention_candidates: list[dict[str, Any]] = []
    for entry in evidence.get("intervention", []) if isinstance(evidence.get("intervention"), list) else []:
        if isinstance(entry, dict):
            intervention_candidates.append({
                **entry,
                "candidate": entry.get("excerpt"),
                "evidence_grade": entry.get("evidence_grade") or intervention_ledger.get("evidence_grade"),
            })
    intervention_value = contract.get("intervention")
    if isinstance(intervention_value, dict):
        intervention_candidates.append({
            "candidate": intervention_value.get("claim"),
            "evidence_grade": intervention_ledger.get("evidence_grade"),
            "evidence_type": intervention_value.get("evidence_type"),
            "candidate_source": "socrates_contract.intervention",
        })
    intervention_candidates.append({
        "candidate": contract.get("input"),
        "candidate_source": "socrates_contract.input",
    })
    intervention_gate = intervention_gate_from_values(intervention_candidates)
    input_variable = _clean_text(intervention_gate.get("selected_intervention"))
    mediator = _clean_text(contract.get("proposed_mediator")) or "the proposed mediator"
    outcome = _clean_text(contract.get("output")) or "the outcome"
    alternatives = [
        _clean_text(item)
        for item in gap.get("alternative_mechanisms", [])
        if _clean_text(item)
    ] if isinstance(gap.get("alternative_mechanisms"), list) else []
    if not intervention_gate.get("admissible"):
        return {
            "status": "blocked_missing_direct_intervention",
            "intervention_type_gate": intervention_gate,
            "counterfactual_experiments": [],
            "first_principles_derivation": [],
            "mechanism_competition": {
                "primary": "unresolved: no admissible intervention -> mediator -> outcome chain",
                "alternatives": alternatives,
                "discriminator": "Retrieve or design a concrete manipulation before generating a causal hypothesis.",
            },
            "evidence_boundary": "Descriptive or review evidence remains rationale and cannot authorize an intervention.",
        }
    return {
        "status": "ready_for_hypothesis_generation",
        "intervention_type_gate": intervention_gate,
        "counterfactual_experiments": [
            {
                "question": f"If {input_variable} is changed while the proposed mediator is suppressed or absent, does {outcome} still change?",
                "design": f"Use matched control, intervention, and mediator-suppression or absence conditions; measure both {mediator} and {outcome}.",
                "prediction_if_mechanism_true": f"Changing {input_variable} changes {mediator}, and the {outcome} effect weakens when {mediator} is blocked or absent.",
                "prediction_if_mechanism_false": f"{outcome} changes independently of {mediator}, or does not respond reproducibly to the intervention.",
                "observability_requirement": "Use a direct measurement of the mediator plus an independent outcome measurement; proxies alone are insufficient.",
            }
        ],
        "first_principles_derivation": [
            {
                "step": f"State the conservation law, thermodynamic potential, kinetic rate law, or governing equation that could connect {input_variable} to {mediator}.",
                "status": "requires domain-specific source or calculation",
            },
            {
                "step": f"Derive a directional prediction for {mediator} -> {outcome} under the intervention and a matched null condition.",
                "status": "requires parameter assumptions and uncertainty bounds",
            },
        ],
        "mechanism_competition": {
            "primary": f"{input_variable} -> {mediator} -> {outcome}",
            "alternatives": alternatives,
            "discriminator": f"Measure the temporal or conditional ordering of {mediator} and {outcome} under independently chosen controls; retain competing mechanisms when the data do not separate them.",
        },
        "evidence_boundary": "This is an experimental and derivational plan, not evidence that the causal claim is already true.",
    }


def normalize_socrates_retrieval_query(query: str) -> str:
    return " ".join(str(query or "").lower().split())


def select_untried_socrates_queries(
    unresolved_fields: list[str],
    query_plan: dict[str, list[str]],
    attempted_queries: set[tuple[str, str]],
    limit: int,
    attempted_retrieval_queries: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Choose untried field-query pairs in deterministic, bounded order."""
    selected: list[tuple[str, str]] = []
    seen_retrieval_queries = set(attempted_retrieval_queries or set())
    for field in unresolved_fields:
        canonical = canonical_mechanism_field(field)
        query = next(
            (
                item
                for item in query_plan.get(canonical, [])
                if (canonical, item) not in attempted_queries
                and normalize_socrates_retrieval_query(item) not in seen_retrieval_queries
            ),
            "",
        )
        duplicate_query = next(
            (
                item
                for item in query_plan.get(canonical, [])
                if (canonical, item) not in attempted_queries
                and normalize_socrates_retrieval_query(item) in seen_retrieval_queries
            ),
            "",
        )
        if duplicate_query:
            log_event(
                "SCIENCE",
                "socrates_duplicate_query_skipped",
                field=canonical,
                query=duplicate_query[:180],
                reason="same_normalized_query_already_retrieved_for_another_mechanism_field",
            )
        if query:
            selected.append((canonical, query))
            seen_retrieval_queries.add(normalize_socrates_retrieval_query(query))
        if len(selected) >= limit:
            break
    return selected


def socrates_targeted_evidence_query_plan(
    query: str,
    *,
    field: str,
    evidence_kind_override: str = "",
) -> list[dict[str, str]]:
    """Return the one-query plan allowed for a Socrates contract repair.

    A missing contract field is not a new request for a field-wide literature
    map.  The caller has already built a query from its intervention,
    mediator, outcome, and the missing evidence lane.  Keeping this plan to
    one provider-neutral causal query prevents the generic review, milestone,
    frontier, and topic-facet planners from spending a separate OpenAlex
    request on each near-duplicate suffix.
    """
    normalized_query = str(query or "").strip()
    normalized_kind = str(evidence_kind_override or field or "mechanism_evidence").strip().lower()
    normalized_kind = re.sub(r"[^a-z0-9]+", "_", normalized_kind).strip("_") or "mechanism_evidence"
    return [
        {
            "branch": f"socrates_targeted_{normalized_kind}",
            "query": normalized_query,
            "l2_query": normalized_query,
            "purpose": "fill one named Socrates contract evidence field with direct, object-aligned literature",
            "query_family": "socrates_targeted_evidence",
            "retrieval_mode": "socrates_targeted_evidence",
            "evidence_kind": str(evidence_kind_override or "").strip(),
        }
    ] if normalized_query else []


def socrates_call_zhizhi_targeted_search(
    *,
    project_id: str,
    query: str,
    domain: str,
    field: str,
    question: str,
    providers: list[str],
    max_results: int,
    imports_per_query: int,
    use_llm: bool,
    preprint_scan_limit: int | None = None,
    preprint_provider_result_target: int = 0,
    preprint_layers: set[str] | None = None,
    layer_quotas: dict[str, int] | None = None,
    alignment_contract: dict[str, Any] | None = None,
    evidence_kind_override: str = "",
    query_branch_override: str = "",
    retrieval_anchor_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one small, persisted ZhiZhi retrieval pass for one evidence question."""
    try:
        from ._literature_import import domain_review_paper, extract_paper_keynote, import_literature_search_result
        from ._literature_search import search_literature_stratified
    except ImportError:
        from _literature_import import domain_review_paper, extract_paper_keynote, import_literature_search_result
        from _literature_search import search_literature_stratified
    output = {
        "field": field,
        "question": question,
        "query": query,
        "searches": 0,
        "imports": 0,
        "paper_ids": [],
        "duplicate_candidates": 0,
        "target_aligned_candidates": 0,
        "targeted_admission": {},
        "retrieval_anchor_contract": dict(retrieval_anchor_contract or {}) if isinstance(retrieval_anchor_contract, dict) else {},
        "query_provenance": {},
        "retrieval_outcome": "not_started",
        "errors": [],
    }
    try:
        if isinstance(retrieval_anchor_contract, dict) and retrieval_anchor_contract:
            provenance = validate_socrates_query_provenance(query, retrieval_anchor_contract)
            output["query_provenance"] = provenance
            if not provenance.get("passes"):
                output["retrieval_outcome"] = "query_contract_invalid"
                output["errors"].append(str(provenance.get("reason") or "query_contract_invalid"))
                log_event(
                    "SCIENCE",
                    "socrates_targeted_query_contract_invalid",
                    project_id=project_id,
                    field=field,
                    rejected_untrusted_terms=provenance.get("rejected_untrusted_terms", []),
                )
                return output
        selected_preprint_layers = (
            SOCRATES_PREPRINT_LAYERS
            if preprint_layers is None
            else {str(item) for item in preprint_layers if str(item)}
        )
        selected_layer_quotas = (
            dict(layer_quotas)
            if isinstance(layer_quotas, dict)
            else direct_evidence_lane_layer_quotas(max_results)
        )
        targeted_query_plan = socrates_targeted_evidence_query_plan(
            query,
            field=field,
            evidence_kind_override=evidence_kind_override,
        )
        search = json.loads(
            search_literature_stratified(
                query=query,
                providers=providers,
                max_results=max_results,
                domain=domain,
                explicit_query_plan=targeted_query_plan,
                use_llm=use_llm,
                layer_quotas=selected_layer_quotas,
                preprint_layers=selected_preprint_layers,
                preprint_scan_limit=preprint_scan_limit,
                preprint_provider_result_target=preprint_provider_result_target,
                preprint_recovery_windows=SOCRATES_PREPRINT_RECOVERY_WINDOWS,
                preprint_recovery_max_variants=SOCRATES_PREPRINT_RECOVERY_MAX_VARIANTS,
                preprint_max_branches=SOCRATES_PREPRINT_MAX_BRANCHES,
                candidate_alignment_contract=alignment_contract,
                requested_evidence_kind=evidence_kind_override,
                retrieval_anchor_contract=retrieval_anchor_contract,
                retrieval_mode="socrates_targeted_evidence",
                # Every Socrates search is for a contract field, so use the
                # stable direct-evidence path even when the missing field is
                # not one of the two initial theory/experiment lanes.
                direct_evidence_mode=True,
            )
        )
        output["searches"] = 1
        output["search_id"] = str(search.get("search_id") or "")
        output["result_count"] = int(search.get("total_results") or 0)
        output["targeted_admission"] = dict(search.get("targeted_admission") or {})
        output["target_aligned_candidates"] = int(
            output["targeted_admission"].get("accepted") or output["result_count"]
        )
        for result_index in range(output["result_count"]):
            if output["imports"] >= imports_per_query:
                break
            try:
                imported = json.loads(
                    import_literature_search_result(
                        project_id,
                        output["search_id"],
                        result_index,
                        use_llm=use_llm,
                        alignment_contract=alignment_contract,
                        evidence_kind_override=evidence_kind_override,
                        query_branch_override=query_branch_override,
                    )
                )
                if str(imported.get("status") or "") == "duplicate":
                    output["duplicate_candidates"] += 1
                    log_event(
                        "SCIENCE",
                        "socrates_duplicate_candidate_skipped",
                        project_id=project_id,
                        field=field,
                        search_id=output["search_id"],
                        result_index=result_index,
                    )
                    continue
                record = imported.get("record") or {}
                paper_id = str(record.get("paper_id") or "") if isinstance(record, dict) else ""
                if paper_id:
                    publication = socrates_publication_assessment(record)
                    if not publication.get("eligible_for_direct_contract"):
                        output["errors"].append(
                            f"formal_publication[{result_index}]:{publication.get('status')}"
                        )
                        log_event(
                            "SCIENCE",
                            "socrates_nonformal_candidate_excluded",
                            project_id=project_id,
                            field=field,
                            paper_id=paper_id,
                            publication_status=publication.get("status"),
                        )
                        continue
                    review = domain_review_paper(project_id, paper_id, target_domain_profile=domain, min_confidence=0.6)
                    if str(review.get("verdict") or "") != "keep":
                        output["errors"].append(f"domain_review[{result_index}]:{review.get('verdict')}")
                        continue
                    output["paper_ids"].append(paper_id)
                    output["imports"] += 1
                    try:
                        extract_paper_keynote(project_id, paper_id=paper_id, use_llm=use_llm)
                    except Exception as exc:
                        output["errors"].append(f"keynote:{exc}")
            except Exception as exc:
                output["errors"].append(f"import[{result_index}]:{exc}")
    except Exception as exc:
        output["errors"].append(f"search:{exc}")
        output["retrieval_outcome"] = "search_error"
        return output

    if output["imports"]:
        output["retrieval_outcome"] = "imported_target_aligned_evidence"
    elif int(output["target_aligned_candidates"] or 0) == 0:
        rejected = int(output["targeted_admission"].get("rejected") or 0)
        output["retrieval_outcome"] = "alignment_rejected" if rejected else "provider_miss"
    elif output["errors"]:
        output["retrieval_outcome"] = "import_failed_or_quality_rejected"
    else:
        output["retrieval_outcome"] = "no_imported_direct_evidence"
    return output


def validate_mechanism_contract_evidence(project: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Remove cited entries that do not belong to the same mechanism context.

    A citation is not accepted merely because it contains a generic field
    marker such as ``control`` or ``intervention``. Invalid evidence is kept in
    an audit trail and the field becomes unresolved, which makes the normal
    Socrates query loop retrieve a targeted replacement.
    """
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    if not evidence:
        return {"valid_fields": [], "rejected": []}
    by_id = {
        str(record.get("paper_id") or ""): record
        for record in project.get("papergraph", [])
        if isinstance(record, dict)
    }
    anchors = _context_terms(
        str(contract.get("context") or ""), str(contract.get("input") or ""),
        str(contract.get("proposed_mediator") or ""), str(contract.get("output") or ""),
    )
    source_bundle = (
        contract.get("mechanism_evidence_bundle")
        if isinstance(contract.get("mechanism_evidence_bundle"), dict)
        else {}
    )
    research_mode = str(
        source_bundle.get("research_mode")
        or contract.get("research_mode")
        or ""
    )
    if not research_mode:
        research_mode = str(
            mode_specific_hypothesis_contract(project, {}, contract, source_bundle).get("mode")
            or UNRESOLVED_RESEARCH_DESIGN
        )
    rejected: list[dict[str, Any]] = []
    valid_fields: list[str] = []
    for field in MECHANISM_FIELDS:
        entries = evidence.get(field, []) if isinstance(evidence.get(field), list) else []
        valid: list[dict[str, Any]] = []
        for entry in entries:
            paper = by_id.get(str(entry.get("paper_id") or ""))
            alignment = socrates_paper_alignment(project, paper or {}, anchors) if paper else {"passes": False}
            if paper and alignment.get("passes"):
                item = dict(entry)
                item["alignment"] = alignment
                publication = socrates_publication_assessment(paper)
                item["publication_assessment"] = publication
                item["publication_status"] = str(publication.get("status") or "")
                if not publication.get("eligible_for_direct_contract"):
                    contract.setdefault("rationale_evidence", {}).setdefault(field, []).append(item)
                    rejected.append({
                        "field": field,
                        "citation": str(entry.get("citation") or ""),
                        "reason": f"formal-publication gate: {publication.get('status')}",
                        "publication_assessment": publication,
                    })
                    continue
                source_design = socrates_source_design(paper)
                item["source_design"] = source_design
                if source_design in {"review", "systematic_review", "meta_analysis", "perspective"}:
                    contract.setdefault("rationale_evidence", {}).setdefault(field, []).append(item)
                    rejected.append({
                        "field": field,
                        "citation": str(entry.get("citation") or ""),
                        "reason": "review_or_perspective_cannot_fill_direct_contract_field",
                    })
                    continue
                item["evidence_role"] = socrates_evidence_role(item, paper)
                if field == "intervention":
                    input_value = mechanism_contract_value(contract, "input")
                    role = classify_input_candidate(
                        input_value,
                        research_mode=research_mode,
                        # This pass validates a record already resolved from
                        # PaperGraph.  The final READY gate separately
                        # requires its paper-qualified source-unit provenance.
                        source_unit_ids=[],
                        require_source_bound=False,
                    )
                    source_supports_input = evidence_entries_trace_value([item], input_value)
                    item["input_role_assessment"] = role
                    if research_mode in {CONTROLLED_INTERVENTION, COMPUTATIONAL_INTERVENTION}:
                        item["intervention_role_assessment"] = role
                    if not role.get("admissible_as_input") or not source_supports_input:
                        contract.setdefault("rationale_evidence", {}).setdefault("intervention", []).append(item)
                        rejected.append({
                            "field": field,
                            "citation": str(entry.get("citation") or ""),
                            "reason": (
                                f"research-mode input ontology gate: {role.get('reason')}"
                                if not role.get("admissible_as_input")
                                else "input phrase is not supported by the cited source excerpt"
                            ),
                            "role_assessment": role,
                        })
                        continue
                valid.append(item)
            else:
                rejected.append({
                    "field": field,
                    "citation": str(entry.get("citation") or ""),
                    "reason": "evidence paper does not share the core mechanism context",
                })
        if valid:
            evidence[field] = valid
            valid_fields.append(field)
        elif entries:
            evidence[field] = []
            contract[field] = "unresolved"
    if rejected:
        contract.setdefault("rejected_evidence", []).extend(rejected)
    contract["evidence_alignment_audit"] = {
        "valid_fields": valid_fields,
        "rejected_count": len(rejected),
        "status": "pass" if not rejected else "replacement_retrieval_required",
    }
    return {"valid_fields": valid_fields, "rejected": rejected}


def _apply_evidence(contract: dict[str, Any], evidence: dict[str, list[dict[str, Any]]]) -> int:
    store = contract.setdefault("evidence", {})
    updated = 0
    for field, entries in evidence.items():
        if not entries or _has_cited_evidence(store.get(field, [])):
            continue
        store[field] = entries
        contract[field] = {
            "status": "evidence_based",
            "claim": str(entries[0].get("excerpt") or ""),
            "citation": str(entries[0].get("citation") or ""),
            "evidence": entries,
        }
        updated += 1
    return updated


def _resolve_gap(project: dict[str, Any], *, gap: dict[str, Any] | str, gap_id: str) -> dict[str, Any]:
    if isinstance(gap, dict) and gap:
        return dict(gap)
    wanted = str(gap_id or gap or "").strip()
    tanxi = project.get("tanxi_gap_analysis", {}) if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    # Ranked TanXi gaps preserve mechanism relevance, TABI and ingredients;
    # prefer them over the older canonical list when both share an id.
    candidates = [item for item in tanxi.get("ranked_gaps", []) if isinstance(item, dict)]
    candidates.extend(
        item for item in tanxi.get("socrates_mechanism_verification_leads", [])
        if isinstance(item, dict)
    )
    candidates.extend(
        item for item in project.get("socrates_mechanism_verification_leads", [])
        if isinstance(item, dict)
    )
    candidates.extend(item for item in project.get("knowledge_gaps", []) if isinstance(item, dict))
    if wanted:
        for item in candidates:
            aliases = {
                str(value).strip()
                for value in (item.get("merged_gap_ids") or [])
                if str(value or "").strip()
            }
            if str(item.get("gap_id") or "") == wanted or wanted in aliases:
                return dict(item)
    if candidates:
        return dict(candidates[0])
    raise ValueError("Socrates requires a TanXi gap or a project with ranked knowledge gaps.")


def _has_cited_evidence(value: Any) -> bool:
    entries = value if isinstance(value, list) else []
    return any(isinstance(entry, dict) and str(entry.get("citation") or "").strip() and str(entry.get("excerpt") or "").strip() for entry in entries)


def _context_terms(*parts: str) -> set[str]:
    terms: set[str] = set()
    for part in parts:
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]{3,}", str(part or "").lower()):
            if token not in _STOPWORDS:
                terms.add(token)
            # Preserve the compound while also exposing entity anchors such as
            # ``SOX2`` in ``SOX2-dependent``.  Without this, a directly matched
            # perturbation ("SOX2 knockout") appears cross-context merely due
            # to hyphenation in the mechanism label.
            for component in re.split(r"[+\-]+", token):
                if len(component) >= 4 and component not in _STOPWORDS:
                    terms.add(component)
    return terms


def _sentences(text: str) -> list[str]:
    sentences = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        clean = _clean_text(sentence)
        if 30 <= len(clean) <= 600:
            sentences.append(clean)
    return sentences


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return _clean_text(value[0]) if value else ""
    return _clean_text(value)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _reading_focus(fields: list[str]) -> dict[str, str]:
    return {
        field: {
            "identity": "definition of the mediator and its causal link to the claimed outcome",
            "location_or_scope": "where the mediator is reported to act and the stated validity regime",
            "dynamics": "time, dose, cycle, scale, or parameter dependence rather than an endpoint-only result",
            "reversibility": "recovery, relaxation, annealing, hysteresis, or explicit irreversibility evidence",
            "observability": "direct measurement signal and instrument, not a proxy endpoint alone",
            "intervention": "a controllable manipulation that changes the mediator",
            "counterfactual": "negative controls, absence-of-mediator comparisons, or mediation tests",
        }.get(field, "source text that directly operationalizes the unresolved mechanism field")
        for field in fields
    }
