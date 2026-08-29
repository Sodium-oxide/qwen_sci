"""Bounded provider routing for project and sub-hypothesis literature discovery.

The module deliberately keeps a broad OpenAlex lane for recall.  Taxonomy-native
filters are an additive, auditable lane and never replace that baseline.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.research_question_contract import (
    MAX_RETRIEVAL_QUERY_TERMS_PER_VARIANT,
    MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT,
    QUESTION_KIND_SPECS,
    SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
    SUPPORTED_QUESTION_KINDS,
    SUPPORTED_RESEARCH_ROLES as SUPPORTED_CONTRACT_RESEARCH_ROLES,
    normalize_science_subhypothesis_v2,
)
from src.pipeline.discipline_taxonomy import (
    resolve_query_variant_discipline_taxonomy,
    resolve_subhypothesis_discipline_taxonomy,
)


RETRIEVAL_LANES_SCHEMA_VERSION = "retrieval_lanes_v1"
SUBHYPOTHESIS_RETRIEVAL_SCHEMA_VERSION = "subhypothesis_retrieval_v6"
SUBHYPOTHESIS_CONTRACT_SCHEMA_VERSION = SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION
SLOT_RECOVERY_TASK_SCHEMA_VERSION = "slot_recovery_task_v1"
SUPPORTED_EVIDENCE_MODES = frozenset(
    {
        "overview",
        "review",
        "empirical",
        "benchmark",
        "mechanism",
        "boundary",
        "latest",
    }
)
_MAX_TERMS = 12
_MAX_SUBHYPOTHESES = 12
_SAFE_QUERY_TERM_REPLACEMENTS = {
    "ion ransport rate": "ion transport rate",
}
_EVIDENCE_QUERY_SUFFIXES = {
    "review": "review",
    "empirical": "experimental study",
    "benchmark": "benchmark evaluation",
    "mechanism": "mechanism",
    "boundary": "failure limitation negative result",
}
def _text(value: Any, *, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _unique_texts(values: Any, *, limit: int = _MAX_TERMS) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    result: list[str] = []
    seen = set()
    for value in values:
        item = _text(value, limit=180)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _provider_filter(
    taxonomy_resolution: Mapping[str, Any] | None,
    provider: str,
) -> dict[str, Any]:
    resolution = _mapping(taxonomy_resolution)
    filters = resolution.get("provider_filters")
    if not isinstance(filters, Mapping):
        return {}
    candidate = filters.get(provider)
    return dict(candidate) if isinstance(candidate, Mapping) else {}


def _has_exact_native_filter(provider_filter: Mapping[str, Any] | None) -> bool:
    payload = _mapping(provider_filter)
    return bool(
        payload.get("applied")
        and payload.get("coverage") == "exact"
        and payload.get("policy") == "hard_filter"
    )


def _normalized_evidence_mode(value: Any) -> str:
    candidate = _text(value, limit=48).casefold().replace("-", "_").replace(" ", "_")
    return candidate if candidate in SUPPORTED_EVIDENCE_MODES else "overview"


def _context_query(context: Mapping[str, Any], query: Any) -> str:
    explicit_query = _text(query)
    if explicit_query:
        return explicit_query
    return _text(
        context.get("original_topic")
        or _mapping(context.get("academic_operationalization")).get("normalized_objective")
    )


def build_query_lanes(
    context: Mapping[str, Any] | None,
    *,
    query: Any = "",
    taxonomy_resolution: Mapping[str, Any] | None = None,
    evidence_mode: Any = "overview",
    lane_prefix: str = "",
    openalex_precision_lanes: Sequence[Mapping[str, Any]] | None = None,
    execution_phase: str = "initial",
    include_arxiv: bool = True,
) -> dict[str, Any]:
    """Build at most four bounded, provenance-ready discovery lanes.

    The broad OpenAlex lane intentionally has no native discipline filter.  A
    provider-native lane is emitted only when the taxonomy explicitly supplies
    an ``exact`` mapping.  This makes ``parent_only``, unresolved, and HSS
    contexts recall-safe by construction.
    """

    payload = _mapping(context)
    resolution = _mapping(taxonomy_resolution) or _mapping(payload.get("taxonomy_resolution"))
    search_query = _context_query(payload, query)
    mode = _normalized_evidence_mode(evidence_mode)
    prefix = _text(lane_prefix, limit=80).strip("._:-")
    lane_name = lambda value: f"{prefix}.{value}" if prefix else value

    operationalization = _mapping(payload.get("academic_operationalization"))
    include_anchors = _unique_texts(
        [
            payload.get("domain"),
            *(
                item.get("label", "")
                for item in payload.get("research_domains", [])
                if isinstance(item, Mapping)
            ),
            *(_mapping(payload.get("domain_context")).get("retrieval_terms") or []),
            *payload.get("core_entities", []),
            *payload.get("retrieval_synonyms", []),
            *(_mapping(payload.get("retrieval_plan")).get("include_anchors") or []),
            operationalization.get("research_object"),
            operationalization.get("task_or_question"),
        ]
    )
    exclude_anchors = _unique_texts(payload.get("exclusion_terms") or [])
    phase = _text(execution_phase, limit=32).casefold() or "initial"
    lanes: list[dict[str, Any]] = [
        {
            "lane_id": lane_name("broad_anchor"),
            "lane": "broad_anchor",
            "provider": "openalex",
            "query": search_query,
            "evidence_mode": mode,
            "taxonomy_coverage": "broad",
            "hard_filter_allowed": False,
            "hard_filter_applied": False,
            "provider_filter": {},
            "purpose": "recall_baseline",
            "discipline_filter_policy": "broad",
            "execution_phase": phase,
        }
    ]

    openalex_filter = _provider_filter(resolution, "openalex")
    default_precision_lanes: list[dict[str, Any]] = []
    if _has_exact_native_filter(openalex_filter):
        default_precision_lanes.append(
            {
                "lane": "exact_discipline",
                "provider_filter": openalex_filter,
                "purpose": "precision_expansion",
                "discipline_filter_policy": "exact_primary",
                "execution_phase": phase,
            }
        )
    precision_lanes = (
        list(openalex_precision_lanes)
        if isinstance(openalex_precision_lanes, Sequence)
        and not isinstance(openalex_precision_lanes, (str, bytes))
        else default_precision_lanes
    )
    for precision_lane in precision_lanes:
        specification = _mapping(precision_lane)
        provider_filter = _mapping(specification.get("provider_filter"))
        if not _has_exact_native_filter(provider_filter):
            continue
        lane = _text(specification.get("lane"), limit=80) or "exact_discipline"
        lanes.append(
            {
                "lane_id": lane_name(lane),
                "lane": lane,
                "provider": "openalex",
                "query": search_query,
                "evidence_mode": mode,
                "taxonomy_coverage": "exact",
                "hard_filter_allowed": True,
                "hard_filter_applied": True,
                "provider_filter": provider_filter,
                "purpose": _text(specification.get("purpose"), limit=120)
                or "precision_expansion",
                "discipline_filter_policy": _text(
                    specification.get("discipline_filter_policy"), limit=80
                )
                or "exact_primary",
                "execution_phase": _text(
                    specification.get("execution_phase"), limit=32
                ).casefold()
                or phase,
            }
        )

    arxiv_filter = _provider_filter(resolution, "arxiv")
    if include_arxiv and _has_exact_native_filter(arxiv_filter):
        lanes.append(
            {
                "lane_id": lane_name("arxiv_frontier"),
                "lane": "arxiv_frontier",
                "provider": "arxiv",
                "query": search_query,
                "evidence_mode": mode,
                "taxonomy_coverage": "exact",
                "hard_filter_allowed": True,
                "hard_filter_applied": True,
                "provider_filter": arxiv_filter,
                "purpose": "conditional_preprint_coverage",
                "discipline_filter_policy": "exact_primary",
                "execution_phase": phase,
            }
        )

    suffix = _EVIDENCE_QUERY_SUFFIXES.get(mode, "")
    if suffix:
        lanes.append(
            {
                "lane_id": lane_name(f"evidence_{mode}"),
                "lane": "evidence_mode",
                "provider": "openalex",
                "query": _text(f"{search_query} {suffix}"),
                "evidence_mode": mode,
                "taxonomy_coverage": "broad",
                "hard_filter_allowed": False,
                "hard_filter_applied": False,
                "provider_filter": {},
                "purpose": "evidence_layer",
                "discipline_filter_policy": "broad",
                "execution_phase": phase,
            }
        )
    elif mode == "latest":
        lanes.append(
            {
                "lane_id": lane_name("evidence_latest"),
                "lane": "evidence_mode",
                "provider": "openalex",
                "query": search_query,
                "evidence_mode": mode,
                "sort": {"publication_date": "desc"},
                "taxonomy_coverage": "broad",
                "hard_filter_allowed": False,
                "hard_filter_applied": False,
                "provider_filter": {},
                "purpose": "evidence_layer",
                "discipline_filter_policy": "broad",
                "execution_phase": phase,
            }
        )

    return {
        "schema_version": RETRIEVAL_LANES_SCHEMA_VERSION,
        "execution_policy": "limited_query_lanes",
        "baseline_query": search_query,
        "normalized_objective": _text(
            operationalization.get("normalized_objective") or search_query
        ),
        "include_anchors": include_anchors,
        "exclude_anchors": exclude_anchors,
        "evidence_mode": mode,
        "query_lanes": lanes,
    }


def build_project_query_lanes(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the retrieval plan for one cached project research context."""

    return build_query_lanes(context)


def _slot_evidence_role(slot_name: str, question_kind: str) -> str:
    """Classify a declared slot for evidence accounting, not scientific truth."""

    name = _text(slot_name, limit=160).casefold()
    if any(token in name for token in ("background", "framework", "review", "context")):
        return "BACKGROUND_CONTEXT"
    if any(token in name for token in ("mechanism", "pathway", "assumption")):
        return "MECHANISTIC_EVIDENCE"
    if any(
        token in name
        for token in (
            "boundary",
            "failure",
            "missing",
            "contradiction",
            "falsification",
            "bias",
            "counterexample",
        )
    ):
        return "LIMITING_OR_CHALLENGING_EVIDENCE"
    if question_kind in {
        "COMPARATIVE_EVALUATION",
        "BOUNDARY_HETEROGENEITY",
        "REPLICATION_CONTRADICTION",
        "MEASUREMENT_VALIDITY",
        "GENERALIZATION_TRANSPORT",
    } or any(
        token in name
        for token in ("comparator", "comparison", "endpoint", "measure", "calibration", "validation")
    ):
        return "COMPARATIVE_OR_MEASUREMENT_EVIDENCE"
    return "DIRECT_OBSERVATION"


def _slot_evidence_mode(evidence_role: str) -> str:
    return {
        "BACKGROUND_CONTEXT": "review",
        "MECHANISTIC_EVIDENCE": "mechanism",
        "LIMITING_OR_CHALLENGING_EVIDENCE": "boundary",
        "COMPARATIVE_OR_MEASUREMENT_EVIDENCE": "benchmark",
        "DIRECT_OBSERVATION": "empirical",
    }.get(evidence_role, "overview")


def _scope_terms(scope: Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in (
        "research_object",
        "population_or_system",
        "condition_or_regime",
        "intervention_or_input",
        "comparison_frame",
        "outcome_or_construct",
        "measurement_or_endpoint",
        "method_or_design",
        "dataset_or_corpus",
        "time_or_scale",
        "theoretical_assumptions",
        "deployment_context",
    ):
        terms.extend(_unique_texts(scope.get(key) or [], limit=4))
    return _unique_texts(terms, limit=12)


def _canonical_query_term(value: Any) -> tuple[str, str]:
    """Apply only explicit, low-risk corrections to a search phrase."""

    term = _text(value, limit=180)
    replacement = _SAFE_QUERY_TERM_REPLACEMENTS.get(term.casefold())
    if replacement:
        return replacement, f"canonicalized_common_typo:{term}->{replacement}"
    if len(term.split()) > 10:
        return term, f"unusually_long_query_phrase:{term}"
    return term, ""


def _normalized_variant_terms(values: Any) -> tuple[list[str], list[str]]:
    raw_values = values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else [values]
    terms: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        term, warning = _canonical_query_term(value)
        key = term.casefold()
        if warning and warning not in warnings:
            warnings.append(warning)
        if not term or key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) >= MAX_RETRIEVAL_QUERY_TERMS_PER_VARIANT:
            break
    return terms, warnings


def _variant_scope_anchors(scope: Mapping[str, Any]) -> list[str]:
    """Keep legacy fallback queries anchored without recreating an intersection."""

    anchors: list[str] = []
    for key in (
        "research_object",
        "population_or_system",
        "outcome_or_construct",
        "measurement_or_endpoint",
    ):
        anchors.extend(_unique_texts(scope.get(key) or [], limit=1))
        if len(anchors) >= 2:
            break
    terms, _warnings = _normalized_variant_terms(anchors)
    return terms[:2]


def _legacy_fallback_query_variants(
    definition: Mapping[str, Any],
    scope: Mapping[str, Any],
    *,
    evidence_role: str,
    question: str,
) -> list[dict[str, Any]]:
    """Produce bounded alternatives for contracts written before variants existed."""

    concepts, concept_warnings = _normalized_variant_terms(
        definition.get("retrieval_concepts") or []
    )
    anchors = _variant_scope_anchors(scope)
    baseline_terms, baseline_warnings = _normalized_variant_terms(
        [*anchors, *(concepts[:1] or [question])]
    )
    variants: list[dict[str, Any]] = []
    seen_queries: set[str] = set()

    def add_variant(variant_id: str, purpose: str, terms: list[str], warnings: list[str]) -> None:
        normalized_terms, term_warnings = _normalized_variant_terms(terms)
        query = _text(" ".join(normalized_terms), limit=1800)
        if not query or query.casefold() in seen_queries:
            return
        seen_queries.add(query.casefold())
        variants.append(
            {
                "variant_id": variant_id,
                "purpose": purpose,
                "query_terms": normalized_terms,
                "query": query,
                "preferred_disciplines": [],
                "evidence_mode": _slot_evidence_mode(evidence_role),
                "query_quality_warnings": _unique_texts(
                    [*warnings, *term_warnings], limit=8
                ),
                "source": "legacy_retrieval_concepts_fallback",
            }
        )

    add_variant(
        "baseline_observation",
        "broad candidate recall from legacy slot concepts",
        baseline_terms,
        [*concept_warnings, *baseline_warnings],
    )
    for index, concept in enumerate(concepts, start=1):
        if len(variants) >= MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT:
            break
        add_variant(
            f"concept_{index}",
            "independent legacy concept recovery path",
            [*anchors, concept],
            concept_warnings,
        )
    return variants


def _slot_query_variants(
    definition: Mapping[str, Any],
    scope: Mapping[str, Any],
    *,
    evidence_role: str,
    question: str,
) -> list[dict[str, Any]]:
    """Compile explicit variants or a recall-safe legacy fallback."""

    raw_variants = definition.get("retrieval_query_variants")
    if not isinstance(raw_variants, Sequence) or isinstance(raw_variants, (str, bytes)):
        return _legacy_fallback_query_variants(
            definition,
            scope,
            evidence_role=evidence_role,
            question=question,
        )
    supplied = [_mapping(item) for item in raw_variants if isinstance(item, Mapping)]
    if not supplied:
        return _legacy_fallback_query_variants(
            definition,
            scope,
            evidence_role=evidence_role,
            question=question,
        )

    baseline_index = next(
        (
            index
            for index, variant in enumerate(supplied)
            if "baseline" in _text(variant.get("variant_id"), limit=80).casefold()
        ),
        0,
    )
    ordered = [supplied[baseline_index], *supplied[:baseline_index], *supplied[baseline_index + 1 :]]
    compiled: list[dict[str, Any]] = []
    for index, variant in enumerate(ordered[:MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT]):
        terms, warnings = _normalized_variant_terms(variant.get("query_terms") or [])
        query = _text(" ".join(terms), limit=1800)
        if not query:
            continue
        compiled.append(
            {
                "variant_id": _text(variant.get("variant_id"), limit=80)
                or f"variant_{index + 1}",
                "purpose": _text(variant.get("purpose"), limit=240)
                or "alternative slot discovery path",
                "query_terms": terms,
                "query": query,
                "preferred_disciplines": _unique_texts(
                    variant.get("preferred_disciplines") or [], limit=3
                ),
                "evidence_mode": _slot_evidence_mode(evidence_role),
                "query_quality_warnings": warnings,
                "source": "slot_definition_retrieval_query_variants",
            }
        )
    return compiled or _legacy_fallback_query_variants(
        definition,
        scope,
        evidence_role=evidence_role,
        question=question,
    )


def _slot_variant_precision_lanes(
    project_resolution: Mapping[str, Any],
    effective_resolution: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    initial_variant: bool,
) -> list[dict[str, Any]]:
    """Keep hard field filters as optional precision complements to broad recall."""

    precision_lanes: list[dict[str, Any]] = []
    primary_filter = _provider_filter(project_resolution, "openalex")
    if initial_variant and _has_exact_native_filter(primary_filter):
        precision_lanes.append(
            {
                "lane": "exact_primary_discipline",
                "provider_filter": primary_filter,
                "purpose": "project-primary precision check",
                "discipline_filter_policy": "exact_primary",
                "execution_phase": "initial",
            }
        )

    adjacent_filter = resolve_query_variant_discipline_taxonomy(
        project_resolution,
        effective_resolution,
        variant.get("preferred_disciplines") or [],
    )
    primary_field_ids = list(primary_filter.get("resolved_field_ids") or [])
    adjacent_field_ids = list(adjacent_filter.get("resolved_field_ids") or [])
    if (
        _has_exact_native_filter(adjacent_filter)
        and adjacent_field_ids
        and adjacent_field_ids != primary_field_ids
    ):
        precision_lanes.append(
            {
                "lane": "adjacent_precision",
                "provider_filter": adjacent_filter,
                "purpose": "cross-disciplinary precision supplement",
                "discipline_filter_policy": "adjacent_precision",
                "execution_phase": "relaxed",
            }
        )
    return precision_lanes


def build_slot_recovery_tasks(
    subhypothesis_contract: Mapping[str, Any],
    *,
    project_context: Mapping[str, Any] | None,
    include_arxiv: bool = True,
) -> list[dict[str, Any]]:
    """Compile one recovery task per declared required slot.

    A task preserves the SH's original evidence contract and routes its own
    query through the same broad/exact provider-lane policy used elsewhere.
    It deliberately does not impose a fixed branch taxonomy.
    """

    contract = _mapping(subhypothesis_contract)
    project = _mapping(project_context)
    identifier = _text(contract.get("sub_hypothesis_id"), limit=120)
    question_kind = _text(contract.get("question_kind"), limit=80).upper()
    scope = _mapping(contract.get("scientific_scope"))
    definitions = _mapping(contract.get("slot_definitions"))
    project_resolution = _mapping(project.get("taxonomy_resolution"))
    # SH decomposition has completed before this point.  Refine the exact
    # OpenAlex discovery lane with the SH's own question/scope/slot concepts,
    # while retaining the project discipline as the primary anchor.
    effective_resolution = resolve_subhypothesis_discipline_taxonomy(
        project_resolution,
        contract,
    )
    effective_context = {
        **project,
        "exclusion_terms": _unique_texts(
            [
                *(project.get("exclusion_terms") or []),
                *(contract.get("exclusion_terms") or []),
            ]
        ),
    }
    tasks: list[dict[str, Any]] = []
    for slot_name in contract.get("required_slots", []):
        slot = _text(slot_name, limit=160)
        definition = _mapping(definitions.get(slot))
        if not slot or not definition:
            continue
        evidence_role = _slot_evidence_role(slot, question_kind)
        task_id = f"{identifier}.{slot}"
        query_variants = _slot_query_variants(
            definition,
            scope,
            evidence_role=evidence_role,
            question=_text(contract.get("question"), limit=1800),
        )
        route_plans: list[dict[str, Any]] = []
        task_lanes: list[dict[str, Any]] = []
        for variant_index, query_variant in enumerate(query_variants):
            initial_variant = variant_index == 0
            variant_id = _text(query_variant.get("variant_id"), limit=80)
            route_plan = build_query_lanes(
                effective_context,
                query=query_variant.get("query"),
                taxonomy_resolution=effective_resolution,
                evidence_mode=query_variant.get("evidence_mode"),
                lane_prefix=f"{task_id}.{variant_id}",
                openalex_precision_lanes=_slot_variant_precision_lanes(
                    project_resolution,
                    effective_resolution,
                    query_variant,
                    initial_variant=initial_variant,
                ),
                execution_phase="initial" if initial_variant else "relaxed",
                # ArXiv is only a conditional discovery lane.  The caller can
                # disable it globally without weakening the OpenAlex-based
                # broad, precision, and evidence-mode retrieval routes.
                include_arxiv=bool(include_arxiv and initial_variant),
            )
            variant_lanes = [
                {
                    **lane,
                    "sub_hypothesis_id": identifier,
                    "slot_recovery_task_id": task_id,
                    "slot_name": slot,
                    "expected_evidence_role": evidence_role,
                    "query_variant_id": variant_id,
                    "query_variant_index": variant_index,
                    "query_variant_purpose": _text(
                        query_variant.get("purpose"), limit=240
                    ),
                    "query_variant_terms": list(
                        query_variant.get("query_terms") or []
                    ),
                    "query_variant_source": _text(
                        query_variant.get("source"), limit=120
                    ),
                    "query_quality_warnings": list(
                        query_variant.get("query_quality_warnings") or []
                    ),
                }
                for lane in route_plan.get("query_lanes", [])
                if isinstance(lane, Mapping)
            ]
            route_plan["query_lanes"] = variant_lanes
            route_plan["query_variant"] = dict(query_variant)
            route_plans.append(route_plan)
            task_lanes.extend(variant_lanes)
        primary_variant = query_variants[0] if query_variants else {}
        route_plan = {
            "schema_version": RETRIEVAL_LANES_SCHEMA_VERSION,
            "execution_policy": "staged_slot_query_variants",
            "baseline_query": _text(primary_variant.get("query"), limit=1800),
            "query_variants": query_variants,
            "variant_route_plans": route_plans,
            "query_lanes": task_lanes,
        }
        tasks.append(
            {
                "schema_version": SLOT_RECOVERY_TASK_SCHEMA_VERSION,
                "task_id": task_id,
                "sub_hypothesis_id": identifier,
                "slot_name": slot,
                "question_kind": question_kind,
                "question": _text(contract.get("question"), limit=1800),
                "scientific_scope": scope,
                "slot_definition": definition,
                "expected_evidence_role": evidence_role,
                "minimum_evidence": _text(definition.get("minimum_evidence"), limit=700),
                "admission_rule": _text(definition.get("admission_rule"), limit=700),
                "challenge_target": _text(contract.get("challenge_target"), limit=1200),
                "design_basis_ids": list(contract.get("design_basis_ids") or []),
                "allowed_evidence_scope": _mapping(contract.get("allowed_evidence_scope")),
                "excluded_evidence_scope": _mapping(contract.get("excluded_evidence_scope")),
                "query": _text(primary_variant.get("query"), limit=1800),
                "query_terms": list(primary_variant.get("query_terms") or []),
                "query_variants": query_variants,
                "effective_taxonomy_resolution": effective_resolution,
                "retrieval_plan": route_plan,
            }
        )
    return tasks


def _flatten_slot_query_lanes(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for task in tasks:
        plan = _mapping(task.get("retrieval_plan"))
        for lane in plan.get("query_lanes", []):
            if isinstance(lane, Mapping):
                lanes.append(dict(lane))
    return lanes


def subhypothesis_decomposition_context_payload(
    project_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bounded project context for an SH decomposition prompt or UI."""

    context = _mapping(project_context)
    operationalization = _mapping(context.get("academic_operationalization"))
    inventory = _mapping(context.get("research_design_inventory"))
    design_basis = [
        {
            "id": _text(item.get("id"), limit=80),
            "kind": _text(item.get("kind"), limit=80),
            "statement": _text(item.get("statement"), limit=500),
            "anchors": _unique_texts(item.get("anchors") or [], limit=6),
        }
        for item in inventory.get("design_basis", [])
        if isinstance(item, Mapping)
    ][:10]
    return {
        "project_context_fingerprint": _text(context.get("input_fingerprint"), limit=128),
        "original_topic": _text(context.get("original_topic")),
        "declared_domain": _text(context.get("declared_domain"), limit=220),
        "domain": _text(context.get("domain"), limit=220),
        "research_domains": [
            _text(item.get("label"), limit=220)
            for item in context.get("research_domains", [])
            if isinstance(item, Mapping)
        ][:5],
        "domain_resolution_source": _text(context.get("domain_resolution_source"), limit=120),
        "requires_human_confirmation": bool(context.get("requires_human_confirmation")),
        "primary_discipline": _text(context.get("primary_discipline"), limit=120),
        "secondary_disciplines": _unique_texts(context.get("secondary_disciplines") or [], limit=3),
        "core_entities": _unique_texts(context.get("core_entities") or []),
        "exclude_anchors": _unique_texts(context.get("exclusion_terms") or []),
        "normalized_objective": _text(operationalization.get("normalized_objective")),
        "research_design_inventory": {
            "schema_version": _text(inventory.get("schema_version"), limit=80),
            "design_basis": design_basis,
        },
        "supported_question_kinds": sorted(SUPPORTED_QUESTION_KINDS),
        "question_kind_requirements": {
            kind: {
                "required_slots": list(spec["required_slots"]),
                "required_scope": list(spec["required_scope"]),
            }
            for kind, spec in QUESTION_KIND_SPECS.items()
        },
        "supported_research_roles": sorted(SUPPORTED_CONTRACT_RESEARCH_ROLES),
        "instruction": (
            "Each sub-hypothesis must cite only design_basis IDs from this inventory. "
            "Use the science_subhypothesis_v2 fields exactly; do not emit legacy SH fields "
            "or invent DB identifiers."
        ),
    }


def build_subhypothesis_context(
    project_context: Mapping[str, Any] | None,
    subhypothesis: Mapping[str, Any],
    *,
    index: int = 0,
    include_arxiv: bool = True,
) -> dict[str, Any]:
    """Compile a validated v2 SH into one retrieval task per required slot."""

    project = _mapping(project_context)
    inventory = _mapping(project.get("research_design_inventory"))
    contract = normalize_science_subhypothesis_v2(
        subhypothesis,
        design_inventory=inventory,
        project_context=project,
    )
    validation = _mapping(contract.get("validation"))
    tasks: list[dict[str, Any]] = []
    if validation.get("valid"):
        tasks = build_slot_recovery_tasks(
            contract,
            project_context=project,
            include_arxiv=include_arxiv,
        )
        if len(tasks) != len(contract.get("required_slots") or []):
            validation = {
                **validation,
                "valid": False,
                "errors": [
                    *list(validation.get("errors") or []),
                    "slot_recovery_task_count_mismatch",
                ],
            }
            contract["validation"] = validation
            tasks = []
    return {
        **contract,
        "retrieval_strategy": "slot_driven_required_slot_recovery",
        "inherited_project_fingerprint": _text(project.get("input_fingerprint"), limit=128),
        "core_entities": _unique_texts(project.get("core_entities") or []),
        "exclusion_terms": _unique_texts(
            [
                *(project.get("exclusion_terms") or []),
                *(contract.get("exclusion_terms") or []),
            ]
        ),
        "effective_taxonomy_resolution": resolve_subhypothesis_discipline_taxonomy(
            _mapping(project.get("taxonomy_resolution")),
            contract,
        ),
        "slot_recovery_tasks": tasks,
        "slot_query_lanes": _flatten_slot_query_lanes(tasks),
    }


def build_subhypothesis_retrieval_plan(
    project_context: Mapping[str, Any] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    *,
    include_arxiv: bool = True,
) -> dict[str, Any]:
    """Build a layered retrieval contract for a bounded SH list without LLM calls."""

    candidates = subhypotheses if isinstance(subhypotheses, Sequence) and not isinstance(subhypotheses, str) else []
    normalized = [
        build_subhypothesis_context(
            project_context,
            candidate,
            index=index,
            include_arxiv=include_arxiv,
        )
        for index, candidate in enumerate(candidates[:_MAX_SUBHYPOTHESES])
    ]
    return {
        "schema_version": SUBHYPOTHESIS_RETRIEVAL_SCHEMA_VERSION,
        "retrieval_strategy": "slot_driven_required_slot_recovery",
        "project_context": subhypothesis_decomposition_context_payload(project_context),
        "subhypotheses": normalized,
    }
