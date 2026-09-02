"""Research-question-aware retrieval planning and paper role assessment."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import re
import time
from typing import Any, Callable, Mapping

try:
    from ._paper_classification import (
        DomainCompatibility,
        assess_paper_domains,
        domain_compatibility,
    )
    from ._science_llm_scheduler import LLMJob, run_science_llm_job
    from ._science_execution_policy import resolve_science_execution_policy
except ImportError:
    from _paper_classification import (
        DomainCompatibility,
        assess_paper_domains,
        domain_compatibility,
    )
    from _science_llm_scheduler import LLMJob, run_science_llm_job
    from _science_execution_policy import resolve_science_execution_policy


QUERY_FAMILIES = (
    (
        "landscape",
        "domain map, terminology, and established mechanisms",
        "review OR survey OR overview",
    ),
    (
        "direct_mechanism",
        "direct causal and mechanistic evidence",
        "mechanism OR causal OR perturbation OR mediation OR necessary OR sufficient",
    ),
    (
        "barrier_failure",
        "barriers, limitations, inefficiency, and anomalous observations",
        "barrier OR limitation OR inefficiency OR resistance OR incomplete OR failure",
    ),
    (
        "counter_evidence",
        "boundary conditions, alternative mechanisms, and contradictory evidence",
        "context dependent OR contradictory OR alternative mechanism OR boundary condition",
    ),
    (
        "frontier",
        "recent frontier work and preprints",
        "recent OR latest OR preprint",
    ),
)

PAPER_DOMAIN_ASSESSMENT_BATCH_SIZE = 16


def paper_domain_assessment_cache_key(paper: Mapping[str, Any]) -> str:
    payload = (
        paper.get("papergraph_input")
        if isinstance(paper.get("papergraph_input"), Mapping)
        else {}
    )
    material = {
        "title": str(paper.get("title") or "").strip(),
        "abstract": str(paper.get("abstract") or "").strip(),
        "venue": str(paper.get("venue") or "").strip(),
        "year": str(paper.get("year") or "").strip(),
        "doi": str(paper.get("doi") or payload.get("doi") or "").strip().lower(),
        "openalex_id": str(
            paper.get("openalex_id") or payload.get("openalex_id") or ""
        ).strip().lower(),
        "publication_types": list(paper.get("publication_types") or []),
        "topics": list(paper.get("topics") or []),
        "concepts": list(paper.get("concepts") or []),
        "fields_of_study": list(
            paper.get("fieldsOfStudy")
            or paper.get("fields_of_study")
            or []
        ),
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return "paper_domain_" + hashlib.sha256(encoded).hexdigest()[:24]


def warm_paper_domain_assessment_cache(
    candidates: list[dict[str, Any]],
    policy: Any,
    cache: dict[str, dict[str, Any]],
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    batch_size: int = PAPER_DOMAIN_ASSESSMENT_BATCH_SIZE,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Classify a deduplicated retrieval pool in bounded concurrent batches."""

    started = time.perf_counter()
    unique_uncached: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    cache_hits = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = paper_domain_assessment_cache_key(candidate)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        existing = candidate.get("paper_domain_assessment")
        if (
            isinstance(existing, Mapping)
            and str(existing.get("schema_version") or "")
            == "paper_domain_assessment_v2"
            and str(existing.get("status") or "")
            in {"CLASSIFIED", "PENDING", "REJECTED_PROTOCOL"}
        ):
            cache[key] = deepcopy(dict(existing))
            cache_hits += 1
            continue
        if key in cache:
            cache_hits += 1
            continue
        unique_uncached.append(candidate)

    resolved_batch_size = max(1, int(batch_size or PAPER_DOMAIN_ASSESSMENT_BATCH_SIZE))
    batches = [
        unique_uncached[offset : offset + resolved_batch_size]
        for offset in range(0, len(unique_uncached), resolved_batch_size)
    ]
    worker_limit = max(
        1,
        min(
            int(max_workers or getattr(policy, "max_inflight", 1) or 1),
            len(batches) or 1,
        ),
    )

    def classify_batch(
        batch_number: int,
        batch: list[dict[str, Any]],
    ) -> tuple[int, list[dict[str, Any]]]:
        batch_identity = hashlib.sha256(
            "|".join(
                paper_domain_assessment_cache_key(candidate)
                for candidate in batch
            ).encode("utf-8")
        ).hexdigest()[:16]
        invoke = lambda: assess_paper_domains(
            batch,
            policy,
            llm_call=llm_call,
        )
        if bool(getattr(policy, "use_llm", False)):
            assessments = run_science_llm_job(
                LLMJob(
                    candidate_id=f"paper_domain_batch_{batch_identity}",
                    stage="paper_domain_assessment_batch",
                    batch_id=f"batch_{batch_number:04d}",
                    prompt_chars=sum(
                        len(str(candidate.get("title") or ""))
                        + len(str(candidate.get("abstract") or ""))
                        for candidate in batch
                    ),
                    max_tokens=max(
                        1200,
                        min(5000, 600 + 420 * len(batch)),
                    ),
                    input_span_count=len(batch),
                ),
                invoke,
            )
        else:
            assessments = invoke()
        return batch_number, [dict(item) for item in assessments]

    completed: dict[int, list[dict[str, Any]]] = {}
    if len(batches) == 1:
        batch_number, assessments = classify_batch(1, batches[0])
        completed[batch_number] = assessments
    elif batches:
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            futures = {
                executor.submit(classify_batch, index, batch): index
                for index, batch in enumerate(batches, start=1)
            }
            for future in as_completed(futures):
                batch_number, assessments = future.result()
                completed[batch_number] = assessments

    for batch_number, batch in enumerate(batches, start=1):
        assessments = completed.get(batch_number, [])
        for candidate, assessment in zip(batch, assessments):
            cache[paper_domain_assessment_cache_key(candidate)] = deepcopy(
                dict(assessment)
            )

    return {
        "schema_version": "paper_domain_assessment_batch_diagnostics_v1",
        "candidate_count": len(seen_keys),
        "uncached_candidate_count": len(unique_uncached),
        "cache_hits": cache_hits,
        "batch_count": len(batches),
        "batch_sizes": [len(batch) for batch in batches],
        "max_workers": worker_limit if batches else 0,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }

# Evidence vocabularies are keyed by the existing RESEARCH_DOMAIN_CATALOG
# domains. They describe how discriminating evidence is commonly expressed;
# they are not venue white-lists and never replace the concrete question.
DOMAIN_EVIDENCE_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "physics": {
        "direct": ("measurement", "experiment", "parameter sweep", "field tuning", "simulation"),
        "method": ("spectroscopy", "scattering", "detector", "numerical simulation", "analytical model"),
    },
    "mathematics": {
        "direct": ("theorem", "proof", "counterexample", "necessary condition", "sufficient condition"),
        "method": ("lemma", "bound", "construction", "asymptotic analysis", "numerical analysis"),
    },
    "computer_science": {
        "direct": ("ablation", "controlled evaluation", "benchmark", "intervention", "distribution shift"),
        "method": ("algorithm", "architecture", "dataset", "evaluation", "complexity analysis"),
    },
    "quantitative_biology": {
        "direct": ("perturbation", "knockout", "inhibition", "rescue", "time course"),
        "method": ("single-cell", "network inference", "mathematical model", "simulation", "omics"),
    },
    "quantitative_finance": {
        "direct": ("stress test", "natural experiment", "regime shift", "counterfactual", "backtest"),
        "method": ("stochastic model", "risk model", "portfolio simulation", "out-of-sample", "robustness"),
    },
    "statistics": {
        "direct": ("identification", "controlled experiment", "counterfactual", "sensitivity analysis", "simulation study"),
        "method": ("estimator", "confidence interval", "error bound", "robustness", "uncertainty quantification"),
    },
    "electrical_engineering": {
        "direct": ("input perturbation", "system identification", "closed-loop experiment", "fault injection", "load test"),
        "method": ("signal processing", "control system", "circuit measurement", "hardware experiment", "simulation"),
    },
    "economics": {
        "direct": ("natural experiment", "instrumental variable", "difference-in-differences", "policy shock", "counterfactual"),
        "method": ("econometric model", "panel data", "field experiment", "robustness", "identification strategy"),
    },
    "medicine": {
        "direct": ("randomized trial", "intervention", "dose response", "treatment comparison", "longitudinal study"),
        "method": ("clinical trial", "cohort", "diagnostic assay", "meta-analysis", "patient stratification"),
    },
    "biology": {
        "direct": ("perturbation", "knockout", "overexpression", "inhibition", "rescue"),
        "method": ("lineage tracing", "time course", "single-cell", "imaging", "multi-omics"),
    },
    "chemistry": {
        "direct": ("concentration", "temperature", "pressure", "catalyst loading", "isotope labeling"),
        "method": ("spectroscopy", "kinetic analysis", "reaction mechanism", "electrochemistry", "characterization"),
    },
    "materials_science": {
        "direct": ("composition", "doping", "temperature", "strain", "processing condition"),
        "method": ("characterization", "microscopy", "spectroscopy", "mechanical testing", "operando measurement"),
    },
    "engineering": {
        "direct": ("design change", "load test", "fault injection", "parameter sweep", "prototype experiment"),
        "method": ("simulation", "prototype", "system test", "optimization", "failure analysis"),
    },
    "agriculture": {
        "direct": ("field experiment", "treatment plot", "controlled environment", "dose response", "management intervention"),
        "method": ("field trial", "remote sensing", "soil analysis", "yield measurement", "longitudinal monitoring"),
    },
    "earth_environmental_science": {
        "direct": ("forcing", "natural experiment", "controlled mesocosm", "scenario perturbation", "source attribution"),
        "method": ("field observation", "remote sensing", "climate model", "tracer", "time series"),
    },
}

_GENERIC_DIRECT_MARKERS = (
    "causal", "mechanism", "mediated", "mediation", "necessary", "sufficient",
    "perturb", "intervention", "controlled experiment", "counterfactual", "rescue",
    "parameter sweep", "sensitivity analysis", "natural experiment",
)
_BOUNDARY_MARKERS = (
    "barrier", "boundary condition", "breakdown", "contradict", "counterexample",
    "failure", "fails", "instability", "limitation", "not robust", "resistance",
    "trade-off", "unexpected", "anomalous", "exception",
)
_METHOD_MARKERS = (
    "algorithm", "benchmark", "dataset", "framework", "inference", "pipeline",
    "protocol", "software", "tool", "workflow", "measurement method", "screening platform",
)

_GENERIC_TERMS = {
    "a", "about", "after", "analysis", "an", "and", "approach", "are", "as", "at", "based", "be", "between", "by",
    "data", "effect", "effects", "for", "from", "into",
    "of", "on", "or", "paper", "papers", "research", "result", "results", "science", "study", "studies",
    "that", "the", "their", "this", "to", "using", "via", "with",
}
_LOW_INFORMATION_SCIENTIFIC_TERMS = {
    "analysis", "cell", "cells", "data", "effect", "factor", "human", "method",
    "model", "models", "network", "result", "study", "system", "systems",
}
_CAUSAL_MARKERS = _GENERIC_DIRECT_MARKERS + (
    "perturb", "knockdown", "knockout", "overexpression", "inhibit", "ablation",
    "lineage tracing", "time course", "proof", "theorem", "identification",
)
_REVIEW_MARKERS = ("review", "survey", "meta-analysis", "perspective", "overview")
_EXPLICIT_NEGATION_MARKERS = (
    "exclude", "excluding", "without", "not including", "not involve", "排除", "不包括", "不含",
)


def _question_contract_anchor_groups(
    contract: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    source = contract if isinstance(contract, Mapping) else {}
    scope = source.get("scientific_scope") if isinstance(source.get("scientific_scope"), Mapping) else {}
    definitions = source.get("slot_definitions") if isinstance(source.get("slot_definitions"), Mapping) else {}
    evidence = source.get("evidence_contract") if isinstance(source.get("evidence_contract"), Mapping) else {}
    claim_target = source.get("claim_target") if isinstance(source.get("claim_target"), Mapping) else {}
    variable_anchors: list[str] = []
    for definition in definitions.values():
        if not isinstance(definition, Mapping):
            continue
        variable_anchors.extend(
            _unique([
                definition.get("meaning"),
                *list(definition.get("retrieval_concepts") or []),
            ])
        )
    return {
        "object": _unique([
            scope.get("research_object"),
            scope.get("population_or_system"),
            scope.get("sample_or_model"),
        ]),
        "target_variable": _unique([
            scope.get("intervention_or_exposure"),
            scope.get("measurement_definition"),
            scope.get("dataset_or_corpus"),
            *variable_anchors,
        ]),
        "outcome": _unique([
            scope.get("outcome_definition"),
            claim_target.get("target_construct"),
        ]),
        "permitted_relations": _unique(evidence.get("permitted_claim_relations")),
        "allowed_evidence_genres": _unique(
            evidence.get("allowed_evidence_genres")
            or ["primary_empirical", "primary_measurement", "primary_validation"]
        ),
    }


def build_research_question_card(
    domain: str,
    objective: str,
    research_brief: str = "",
    query: str = "",
    research_question_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a catalog-grounded, discipline-neutral retrieval contract."""
    try:
        from ._models import (
            RESEARCH_DOMAIN_CATALOG,
            research_domain_profile,
            research_domain_subfield_topics,
            resolve_project_research_domains,
        )
    except ImportError:
        from _models import (
            RESEARCH_DOMAIN_CATALOG,
            research_domain_profile,
            research_domain_subfield_topics,
            resolve_project_research_domains,
        )
    source = " ".join(
        str(value).strip()
        for value in (domain, objective, research_brief, query)
        if str(value or "").strip()
    )
    question_text = " ".join(
        str(value).strip()
        for value in (query, objective, domain)
        if str(value or "").strip()
    )
    core_terms = _significant_terms(question_text, limit=20)
    core_phrases = _significant_phrases(" ".join((query, objective)), limit=16)
    catalog_profile = research_domain_profile(source)
    domain_resolution = resolve_project_research_domains(
        domain,
        objective or query,
        research_brief,
        min_domains=1,
        max_domains=5,
    )
    catalog_subfields = research_domain_subfield_topics(source, max_topics=4, terms_per_topic=5)
    resolved_domains = list(
        dict.fromkeys(
            [
                str(item)
                for item in domain_resolution.get("interdisciplinary_profile", {}).get("active_domains", [])
                if str(item) in RESEARCH_DOMAIN_CATALOG
            ]
            + [
                str(item)
                for item in catalog_profile.get("active_domains", [])
                if str(item) in RESEARCH_DOMAIN_CATALOG
            ]
        )
    )
    catalog_terms = _unique(
        [
            str(term)
            for item in domain_resolution.get("research_domains", [])
            if isinstance(item, dict)
            for term in item.get("matched_terms", [])
        ]
        + [
            str(term)
            for topic in catalog_subfields
            if isinstance(topic, dict)
            for term in topic.get("terms", [])
        ]
    )[:24]
    direct_evidence_terms = _domain_profile_terms(resolved_domains, "direct", limit=14)
    method_evidence_terms = _domain_profile_terms(resolved_domains, "method", limit=12)
    explicit_exclusions = _explicit_exclusion_terms(source)
    declared_domain_contract = (
        dict(research_question_contract.get("research_domain_contract") or {})
        if isinstance(research_question_contract, Mapping)
        and isinstance(research_question_contract.get("research_domain_contract"), Mapping)
        else {}
    )
    domain_reason_codes: list[str] = []
    if not resolved_domains:
        domain_reason_codes.append("QUESTION_DOMAIN_UNRESOLVED")
    domain_anchors = _unique([
        *list(declared_domain_contract.get("evidence_anchors") or []),
        *catalog_terms,
        *core_phrases,
    ])[:24]
    research_domain_contract = declared_domain_contract or {
        "schema_version": "research_domain_contract_v1",
        "status": "READY" if resolved_domains and domain_anchors else "PENDING",
        "primary_domain_id": str(domain_resolution.get("primary_domain") or ""),
        "active_domain_ids": resolved_domains,
        "taxonomy_nodes": [
            {
                "taxonomy": "internal_research_domain_catalog",
                "id": "/".join(
                    part for part in (
                        str(item.get("domain") or ""),
                        str(item.get("subfield") or ""),
                    ) if part
                ),
                "label": str(item.get("label") or item.get("domain") or ""),
            }
            for item in domain_resolution.get("research_domains", [])
            if isinstance(item, dict) and str(item.get("domain") or "")
        ],
        "source": "project_domain_resolution",
        "evidence_anchors": domain_anchors,
        "confidence": 0.0,
        "reason_codes": domain_reason_codes,
    }
    contract_anchor_groups = _question_contract_anchor_groups(
        research_question_contract
    )
    return {
        "version": "retrieval_strategy_v3_domain_contract",
        "research_question": str(objective or query or domain).strip(),
        "domain": str(domain or "").strip(),
        "core_terms": core_terms,
        "core_phrases": core_phrases,
        "research_domain_contract": research_domain_contract,
        "contract_anchor_groups": contract_anchor_groups,
        "catalog_subfields": catalog_subfields,
        "catalog_terms": catalog_terms,
        "causal_questions": [
            "What is necessary or sufficient for the proposed effect?",
            "What mediates the relationship, and what alternative paths remain plausible?",
            "Under which system, regime, scale, time, or boundary condition does the relationship fail?",
        ],
        "accepted_evidence": direct_evidence_terms or list(_GENERIC_DIRECT_MARKERS[:8]),
        "method_evidence": method_evidence_terms,
        "boundary_policy": {
            "explicit_exclusion_terms": explicit_exclusions,
            "cross_domain_bridge_allowed": True,
            "requires_transferability_justification": True,
            "requires_human_confirmation": bool(domain_resolution.get("requires_human_confirmation")),
            "instruction": "Assign cross-system papers by mechanism transferability; a top-level discipline match alone is insufficient.",
        },
        "paper_role_policy": {
            "CORE_DIRECT": "Matches the declared object, target variable, outcome, relation, domain, and evidence genre.",
            "COMPONENT_SUPPORT": "Supplies a transferable component or mechanism but cannot alone support the core claim.",
            "BOUNDARY": "Tests a limitation, counterexample, failure regime, or contradictory observation tied to the question.",
            "ADVERSE": "Provides directly relevant adverse or reversing evidence.",
            "BACKGROUND": "Supplies a relevant map or review but cannot occupy a causal-evidence slot.",
            "METHOD": "Supplies a relevant method only; it is not automatically imported as mechanism evidence.",
            "PENDING": "Requires domain, evidence-genre, or full-text contract confirmation.",
            "OFF_TOPIC": "Shares only broad vocabulary or a top-level discipline and is not automatically imported.",
        },
    }


def with_retrieval_query(card: dict[str, Any] | None, query: str) -> dict[str, Any]:
    """Merge the provider-safe retrieval query into a durable question card."""
    normalized = dict(card or {})
    existing_terms = [str(item) for item in normalized.get("core_terms", []) if str(item).strip()]
    normalized["core_terms"] = _unique(_significant_terms(query, limit=18) + existing_terms)[:24]
    existing_phrases = [str(item) for item in normalized.get("core_phrases", []) if str(item).strip()]
    normalized["core_phrases"] = _unique(_significant_phrases(query, limit=14) + existing_phrases)[:20]
    normalized["retrieval_query"] = str(query or "").strip()
    normalized.setdefault("version", "retrieval_strategy_v3_domain_contract")
    normalized.setdefault("boundary_policy", {})
    normalized.setdefault("paper_role_policy", {})
    return normalized


def build_purposeful_query_plan(
    query: str,
    question_card: dict[str, Any] | None = None,
    focus_branches: list[str] | None = None,
    max_branches: int = 5,
) -> list[dict[str, str]]:
    """Create bounded query families with an explicit scientific purpose."""
    base_query = _normalize_space(query)
    if not base_query:
        return []
    plan: list[dict[str, str]] = []
    for branch, purpose, suffix in QUERY_FAMILIES[: max(1, max_branches)]:
        effective_suffix = _query_family_suffix(branch, suffix, question_card)
        plan.append(
            {
                "branch": branch,
                "query": f"({base_query}) AND ({effective_suffix})",
                "purpose": purpose,
                "query_family": branch,
                "catalog_domains": list((question_card or {}).get("research_domain_contract", {}).get("active_domain_ids", [])),
            }
        )
    for topic in (question_card or {}).get("catalog_subfields", [])[:2]:
        if not isinstance(topic, dict):
            continue
        terms = [str(term) for term in topic.get("terms", []) if str(term).strip()]
        if not terms:
            continue
        plan.append(
            {
                "branch": f"catalog_{topic.get('domain')}_{topic.get('subfield')}",
                "query": f"({base_query}) AND ({' OR '.join(terms[:4])})",
                "purpose": "cover a catalog-matched subfield without broadening the core question to unrelated disciplines",
                "query_family": "catalog_subfield",
            }
        )
    for index, focus in enumerate(focus_branches or []):
        focus_text = _normalize_space(focus)
        if not focus_text:
            continue
        plan.append(
            {
                "branch": f"user_focus_{index + 1}",
                "query": f"({base_query}) AND ({focus_text})",
                "purpose": "user-specified subproblem or missing evidence branch",
                "query_family": "user_focus",
            }
        )
    boundary_policy = (question_card or {}).get("boundary_policy", {})
    bridge_terms = [str(item) for item in boundary_policy.get("bridge_terms", []) if str(item).strip()]
    if bridge_terms:
        plan.append(
            {
                "branch": "bridge_context",
                "query": f"({base_query}) AND ({' OR '.join(bridge_terms[:3])}) AND (mechanism OR pathway)",
                "purpose": "retrieve transferable bridge evidence separately from the core corpus",
                "query_family": "bridge_context",
            }
        )
    return _dedupe_query_plan(plan)


def classify_paper_research_role(
    result: dict[str, Any],
    question_card: dict[str, Any] | None,
    *,
    policy: Any | None = None,
    llm_call: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind a paper role to explicit domain and contract-axis evidence."""
    card = question_card or {}
    boundary_policy = card.get("boundary_policy", {}) if isinstance(card.get("boundary_policy"), dict) else {}
    text = _paper_text(result)
    domain_gate = result.get("domain_gate", {}) if isinstance(result.get("domain_gate"), dict) else {}
    if str(domain_gate.get("verdict") or "").lower() == "reject":
        return _role("OFF_TOPIC", 0.0, "The final domain gate rejected this candidate.", "excluded", auto_selectable=False)
    explicit_exclusions = [str(item).lower() for item in boundary_policy.get("explicit_exclusion_terms", []) if str(item).strip()]
    matched_exclusions = [term for term in explicit_exclusions if _contains_term(text, term)]
    if matched_exclusions:
        return _role(
            "OFF_TOPIC",
            0.0,
            f"Candidate matches explicit project exclusion terms: {', '.join(matched_exclusions)}.",
            "excluded",
            auto_selectable=False,
        )
    core_terms = [str(item).lower() for item in card.get("core_terms", []) if len(str(item).strip()) >= 3]
    specific_core_terms = [term for term in core_terms if term not in _LOW_INFORMATION_SCIENTIFIC_TERMS]
    core_hits = [term for term in specific_core_terms if _contains_term(text, term)]
    phrase_hits = [
        str(item).lower()
        for item in card.get("core_phrases", [])
        if len(str(item).split()) >= 2 and _contains_term(text, str(item).lower())
    ]
    catalog_hits = [
        str(item).lower()
        for item in card.get("catalog_terms", [])
        if len(str(item).strip()) >= 3 and _contains_term(text, str(item).lower())
    ]
    evidence_markers = _unique(
        list(_CAUSAL_MARKERS)
        + [str(item).lower() for item in card.get("accepted_evidence", []) if str(item).strip()]
    )
    method_markers = _unique(
        list(_METHOD_MARKERS)
        + [str(item).lower() for item in card.get("method_evidence", []) if str(item).strip()]
    )
    causal_hits = [marker for marker in evidence_markers if _contains_term(text, marker)]
    boundary_hits = [marker for marker in _BOUNDARY_MARKERS if _contains_term(text, marker)]
    method_hits = [marker for marker in method_markers if _contains_term(text, marker)]
    paper_domain_assessment = (
        result.get("paper_domain_assessment")
        if isinstance(result.get("paper_domain_assessment"), Mapping)
        else None
    )
    if paper_domain_assessment is None:
        effective_policy = policy or resolve_science_execution_policy({})
        paper_domain_assessment = assess_paper_domains(
            [result], effective_policy, llm_call=llm_call
        )[0]
    catalog_assessment = _catalog_domain_assessment(result, card)
    compatibility = domain_compatibility(
        card.get("research_domain_contract"), paper_domain_assessment
    )
    domain_overlap = compatibility == DomainCompatibility.MATCH
    question_link_strength = 2 * len(phrase_hits) + len(core_hits)
    signal_payload = {
        "core_hits": core_hits,
        "phrase_hits": phrase_hits,
        "catalog_hits": catalog_hits,
        "causal_hits": causal_hits,
        "boundary_hits": boundary_hits,
        "method_hits": method_hits,
        "question_domains": catalog_assessment["question_domains"],
        "paper_domains": catalog_assessment["paper_domains"],
        "domain_overlap": catalog_assessment["overlap"],
        "domain_compatibility": compatibility.value,
        "paper_domain_assessment": dict(paper_domain_assessment),
    }

    if compatibility == DomainCompatibility.UNKNOWN:
        return _role(
            "PENDING",
            0.2,
            "Question or paper domain classification is not ready; unknown domain is not treated as compatible.",
            "domain_pending",
            auto_selectable=True,
            pending_full_text_verification=True,
            reason_codes=["DOMAIN_CLASSIFICATION_PENDING"],
            **signal_payload,
        )

    # A top-level discipline hit or low-information words such as "cell",
    # "network", or "model" cannot establish a research-question link.
    if question_link_strength <= 0:
        return _role(
            "OFF_TOPIC",
            0.05,
            "Candidate shares at most a broad discipline or low-information vocabulary, not the bounded research question.",
            "excluded_from_automatic_import",
            auto_selectable=False,
            **signal_payload,
        )

    if compatibility == DomainCompatibility.MISMATCH:
        if boundary_hits and (phrase_hits or len(core_hits) >= 2):
            return _role(
                "BOUNDARY",
                min(0.72, 0.42 + 0.05 * question_link_strength + 0.04 * len(boundary_hits)),
                "Candidate is outside the resolved catalog domains but tests a question-linked boundary or failure regime.",
                "cross_domain_boundary_evidence",
                auto_selectable=True,
                transferability_required=True,
                **signal_payload,
            )
        if causal_hits and (phrase_hits or len(core_hits) >= 2):
            return _role(
                "COMPONENT_SUPPORT",
                min(0.74, 0.4 + 0.05 * question_link_strength + 0.03 * len(causal_hits)),
                "Candidate is cross-domain but contains a question-linked mechanism; transferability must be justified explicitly.",
                "cross_domain_mechanistic_bridge",
                auto_selectable=True,
                transferability_required=True,
                **signal_payload,
            )
        return _role(
            "OFF_TOPIC",
            0.1 + min(0.15, 0.03 * question_link_strength),
            "Candidate belongs to different catalog domains and lacks a strong transferable mechanism or boundary test.",
            "excluded_from_automatic_import",
            auto_selectable=False,
            transferability_required=True,
            **signal_payload,
        )

    if boundary_hits and (phrase_hits or len(core_hits) >= 2):
        return _role(
            "BOUNDARY",
            min(0.86, 0.52 + 0.05 * question_link_strength + 0.04 * len(boundary_hits)),
            "Candidate is context-compatible and tests a linked limitation, counterexample, or failure regime.",
            "boundary_or_counterevidence",
            auto_selectable=True,
            **signal_payload,
        )

    method_requested = any(
        _contains_term(
            " ".join((str(card.get("research_question") or ""), str(card.get("retrieval_query") or ""))).lower(),
            marker,
        )
        for marker in method_markers
    )
    if method_hits and not causal_hits and not method_requested:
        return _role(
            "METHOD",
            min(0.62, 0.28 + 0.05 * question_link_strength + 0.02 * len(method_hits)),
            "Candidate contributes a question-linked method but not direct mechanism evidence.",
            "method_only_not_automatic_mechanism_evidence",
            auto_selectable=False,
            **signal_payload,
        )

    anchor_groups = card.get("contract_anchor_groups") if isinstance(card.get("contract_anchor_groups"), Mapping) else {}
    object_hits = [
        anchor for anchor in anchor_groups.get("object", [])
        if _contains_term(text, str(anchor))
    ]
    variable_hits = [
        anchor for anchor in anchor_groups.get("target_variable", [])
        if _contains_term(text, str(anchor))
    ]
    outcome_hits = [
        anchor for anchor in anchor_groups.get("outcome", [])
        if _contains_term(text, str(anchor))
    ]
    paper_classification = result.get("paper_classification") if isinstance(result.get("paper_classification"), Mapping) else {}
    evidence_genre = str(paper_classification.get("evidence_genre") or "unknown")
    allowed_genres = {
        str(item) for item in anchor_groups.get("allowed_evidence_genres", []) if str(item)
    }
    axis_payload = {
        "object_anchor_hits": object_hits,
        "target_variable_anchor_hits": variable_hits,
        "outcome_anchor_hits": outcome_hits,
        "evidence_genre": evidence_genre,
    }
    core_axis_match = bool(object_hits and variable_hits and outcome_hits)
    genre_confirmed = bool(evidence_genre != "unknown" and evidence_genre in allowed_genres)
    if core_axis_match and genre_confirmed:
        return _role(
            "CORE_DIRECT",
            min(1.0, 0.58 + 0.06 * question_link_strength + 0.03 * len(causal_hits)),
            "Candidate matches the declared object, target variable, outcome, domain, and allowed evidence genre.",
            "core_direct_evidence_candidate",
            auto_selectable=True,
            **axis_payload,
            **signal_payload,
        )
    if core_axis_match and not genre_confirmed:
        return _role(
            "PENDING",
            min(0.68, 0.38 + 0.04 * question_link_strength),
            "Contract axes match, but full-text evidence genre confirmation is pending.",
            "background_pending",
            auto_selectable=True,
            pending_full_text_verification=True,
            reason_codes=["EVIDENCE_GENRE_CONFIRMATION_PENDING"],
            **axis_payload,
            **signal_payload,
        )

    if evidence_genre in {"systematic_review", "narrative_review", "contextual_synthesis"} and question_link_strength >= 2:
        return _role(
            "BACKGROUND",
            min(0.68, 0.32 + 0.05 * question_link_strength),
            "Candidate maps a question-linked literature area but cannot occupy a causal-evidence slot.",
            "landscape_or_rationale_only",
            auto_selectable=True,
            **signal_payload,
        )

    if causal_hits and (phrase_hits or core_hits):
        return _role(
            "COMPONENT_SUPPORT",
            min(0.7, 0.34 + 0.05 * question_link_strength + 0.03 * len(causal_hits)),
            "Candidate has a partial question-linked mechanism and is retained as bridge evidence, not direct support.",
            "mechanistic_bridge",
            auto_selectable=True,
            transferability_required=not domain_overlap,
            **signal_payload,
        )

    return _role(
        "OFF_TOPIC",
        0.12 + min(0.12, 0.03 * question_link_strength),
        "Candidate has insufficient bounded topic and evidence alignment for automatic import.",
        "excluded_from_automatic_import",
        auto_selectable=False,
        **axis_payload,
        **signal_payload,
    )


def prioritize_candidates_for_question_card(
    candidates: list[dict[str, Any]],
    question_card: dict[str, Any] | None,
    *,
    use_llm: bool | None = None,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    domain_assessment_cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Annotate and prioritize CORE evidence while preserving bridge candidates."""
    if not question_card:
        return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
    source_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    policy = resolve_science_execution_policy({}, use_llm=use_llm)
    shared_cache = (
        domain_assessment_cache
        if isinstance(domain_assessment_cache, dict)
        else {}
    )
    warm_paper_domain_assessment_cache(
        source_candidates,
        policy,
        shared_cache,
        llm_call=llm_call,
    )
    assessments: list[dict[str, Any] | None] = [None] * len(source_candidates)
    for index, candidate in enumerate(source_candidates):
        existing = candidate.get("paper_domain_assessment")
        if (
            isinstance(existing, Mapping)
            and str(existing.get("schema_version") or "") == "paper_domain_assessment_v2"
            and str(existing.get("status") or "") in {"CLASSIFIED", "PENDING", "REJECTED_PROTOCOL"}
        ):
            assessments[index] = dict(existing)
        else:
            cached = shared_cache.get(
                paper_domain_assessment_cache_key(candidate)
            )
            assessments[index] = dict(cached or {})
    prepared: list[dict[str, Any]] = []
    for candidate, domain_assessment in zip(source_candidates, assessments):
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        item["paper_domain_assessment"] = dict(domain_assessment or {})
        assessment = classify_paper_research_role(
            item, question_card, policy=policy, llm_call=llm_call
        )
        item["research_role"] = assessment["role"]
        item["research_role_assessment"] = assessment
        item["research_role_priority"] = _role_priority(assessment["role"])
        item["research_role_auto_selectable"] = bool(assessment.get("auto_selectable", True))
        prepared.append(item)
    prepared.sort(
        key=lambda item: (
            -int(item.get("research_role_priority") or 0),
            -float((item.get("research_role_assessment") or {}).get("score") or 0.0),
            -float(item.get("relevance_score") or 0.0),
            str(item.get("title") or ""),
        )
    )
    return prepared


def summarize_retrieval_role_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        role: 0
        for role in (
            "CORE_DIRECT", "COMPONENT_SUPPORT", "BOUNDARY", "ADVERSE",
            "BACKGROUND", "METHOD", "PENDING", "OFF_TOPIC",
        )
    }
    purpose_counts: dict[str, int] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        role = str(result.get("research_role") or "PENDING").upper()
        if role in counts:
            counts[role] += 1
        purpose = str(result.get("query_branch") or result.get("query_family") or "unspecified")
        purpose_counts[purpose] = purpose_counts.get(purpose, 0) + 1
    missing_core_families = [
        branch
        for branch, _, _ in QUERY_FAMILIES
        if purpose_counts.get(branch, 0) == 0
    ]
    return {
        "paper_roles": counts,
        "query_family_result_counts": purpose_counts,
        "missing_query_families": missing_core_families,
        "requires_follow_up": bool(
            missing_core_families or counts["CORE_DIRECT"] == 0
        ),
    }


def _role(
    role: str,
    score: float,
    reason: str,
    allowed_use: str,
    **signals: Any,
) -> dict[str, Any]:
    retained_signals: dict[str, Any] = {}
    for key, value in signals.items():
        if value is None:
            continue
        if isinstance(value, (str, list, tuple, dict, set)) and not value:
            continue
        # False is meaningful for auto_selectable and must not be discarded.
        retained_signals[key] = value
    return {
        "role": role,
        "score": round(score, 4),
        "reason": reason,
        "allowed_use": allowed_use,
        **retained_signals,
    }


def _role_priority(role: str) -> int:
    return {
        "CORE_DIRECT": 6,
        "BOUNDARY": 5,
        "ADVERSE": 5,
        "COMPONENT_SUPPORT": 4,
        "BACKGROUND": 3,
        "METHOD": 2,
        "PENDING": 1,
        "OFF_TOPIC": 0,
    }.get(str(role).upper(), 1)


def _paper_text(result: dict[str, Any]) -> str:
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    values = []
    for key in ("title", "abstract", "conclusion", "contribution", "limitation", "method", "scenario", "benchmark", "venue"):
        values.append(str(result.get(key) or payload.get(key) or ""))
    return _normalize_space(" ".join(values)).lower()


def _significant_terms(text: str, limit: int) -> list[str]:
    phrases = [match.strip().lower() for match in re.findall(r'"([^\"]{3,80})"', str(text or ""))]
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", str(text or ""))
        if word.lower() not in _GENERIC_TERMS
    ]
    return _unique(phrases + words)[:limit]


def _significant_phrases(text: str, limit: int) -> list[str]:
    quoted = [match.strip().lower() for match in re.findall(r'"([^\"]{3,80})"', str(text or ""))]
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", str(text or ""))
        if word.lower() not in _GENERIC_TERMS
    ]
    phrases: list[str] = []
    for width in (3, 2):
        for index in range(0, max(0, len(words) - width + 1)):
            tokens = words[index : index + width]
            if not any(token not in _LOW_INFORMATION_SCIENTIFIC_TERMS for token in tokens):
                continue
            phrases.append(" ".join(tokens))
    return _unique(quoted + phrases)[: max(0, int(limit))]


def _domain_profile_terms(domains: list[str], kind: str, limit: int) -> list[str]:
    values: list[str] = []
    for domain in domains:
        values.extend(DOMAIN_EVIDENCE_PROFILES.get(str(domain), {}).get(str(kind), ()))
    return _unique(values)[: max(0, int(limit))]


def _query_family_suffix(
    branch: str,
    fallback: str,
    question_card: dict[str, Any] | None,
) -> str:
    if branch != "direct_mechanism":
        return fallback
    active_domains = [
        str(item)
        for item in (question_card or {}).get("research_domain_contract", {}).get("active_domain_ids", [])
        if str(item).strip()
    ]
    evidence_terms = _domain_profile_terms(active_domains, "direct", limit=4)
    terms = _unique(evidence_terms + ["mechanism", "causal", "necessary", "sufficient"])
    return " OR ".join(terms[:6]) or fallback


def _explicit_exclusion_terms(text: str) -> list[str]:
    normalized = _normalize_space(text)
    exclusions: list[str] = []
    for marker in _EXPLICIT_NEGATION_MARKERS:
        for match in re.finditer(re.escape(marker), normalized, flags=re.IGNORECASE):
            tail = normalized[match.end() : match.end() + 100]
            tail = re.split(r"[.;:!?，。；：！？]", tail, maxsplit=1)[0]
            tail = re.split(r"\b(?:but|while|except|unless)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
            candidate = _normalize_space(tail.strip(" ,:-"))
            if candidate:
                exclusions.extend(_significant_phrases(candidate, limit=2))
                exclusions.extend(_significant_terms(candidate, limit=4))
    return _unique(exclusions)[:12]


def _catalog_domain_assessment(
    result: Mapping[str, Any],
    card: dict[str, Any],
) -> dict[str, list[str]]:
    question_contract = (
        card.get("research_domain_contract")
        if isinstance(card.get("research_domain_contract"), Mapping)
        else {}
    )
    paper_assessment = (
        result.get("paper_domain_assessment")
        if isinstance(result.get("paper_domain_assessment"), Mapping)
        else {}
    )
    question_domains = [
        str(item)
        for item in question_contract.get("active_domain_ids", [])
        if str(item).strip()
    ]
    paper_domains = [
        str(item)
        for item in paper_assessment.get("active_domain_ids", [])
        if str(item).strip()
    ]
    overlap = sorted(set(question_domains) & set(paper_domains))
    return {
        "question_domains": question_domains,
        "paper_domains": paper_domains,
        "overlap": overlap,
    }


def _contains_term(text: str, term: str) -> bool:
    haystack = _normalize_space(text).lower()
    needle = _normalize_space(term).lower()
    if not haystack or not needle:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9 _+\-/]*", needle):
        return needle in haystack
    token_patterns: list[str] = []
    for token in re.findall(r"[a-z0-9]+", needle):
        pattern = re.escape(token)
        if len(token) > 3 and not token.endswith("s"):
            pattern += r"(?:s|es)?"
        token_patterns.append(pattern)
    if not token_patterns:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s_+\-/]+".join(token_patterns) + r"(?![a-z0-9])"
    return bool(re.search(pattern, haystack))


def _dedupe_query_plan(plan: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in plan:
        query = _normalize_space(str(item.get("query") or ""))
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        copied = dict(item)
        copied["query"] = query
        deduped.append(copied)
    return deduped


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = _normalize_space(value)
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        unique_values.append(normalized)
    return unique_values


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
